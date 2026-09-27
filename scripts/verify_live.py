"""Run the production agent pipeline against NVIDIA using isolated synthetic inputs.

No canned provider responses. Leaves an auditable validation database in data/.
Requires NVIDIA_API_KEY in .env. Never prints credentials or reasoning tokens.
"""

import argparse
import asyncio
import json
import secrets
import time
from datetime import datetime, timezone

from backend.agents import NVIDIAAgentRunner, RunWorker
from backend.config import ROOT, Settings
from backend.db import Database, now, uid
from backend.security import password_hash
from scripts.seed_demo import seed


async def main():
    parser = argparse.ArgumentParser(description="Verify the real agent pipeline on isolated sample inputs.")
    parser.add_argument("--model", help="Override the configured NVIDIA model for this test only")
    parser.add_argument(
        "--thinking",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Override extended reasoning for this test",
    )
    parser.add_argument("--max-tokens", type=int, help="Override the response token budget")
    parser.add_argument("--scenario", choices=("available", "stockout"), default="available")
    options = parser.parse_args()
    overrides = {}
    if options.model:
        overrides["nvidia_model"] = options.model
    if options.thinking is not None:
        overrides["nvidia_enable_thinking"] = options.thinking
    if options.max_tokens is not None:
        overrides["nvidia_max_tokens"] = options.max_tokens
    settings = Settings(**overrides)
    if not settings.nvidia_api_key.get_secret_value():
        raise SystemExit("NVIDIA_API_KEY is missing")
    path = ROOT / "data" / f"validation-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}.sqlite3"
    db = Database(str(path))
    seed(db)
    run_id, user_id = uid(), uid()
    with db.transaction() as connection:
        if options.scenario == "stockout":
            connection.execute("UPDATE parts SET stock=0")
        connection.execute(
            "INSERT INTO users VALUES(?,?,?,?)",
            (user_id, "validation-only", password_hash(secrets.token_urlsafe(32)), "admin"),
        )
        connection.execute(
            "INSERT INTO runs(id,asset_id,status,created_at,requested_by) VALUES(?,?,?,?,?)",
            (run_id, "MTR-042", "running", now(), user_id),
        )
    runner = NVIDIAAgentRunner(settings, db)
    worker = RunWorker(db, runner)
    print(
        f"Starting {settings.nvidia_model}; thinking={settings.nvidia_enable_thinking}; scenario={options.scenario}. Run: {run_id}",
        flush=True,
    )
    started = time.perf_counter()
    task = asyncio.create_task(worker.execute({"id": run_id, "asset_id": "MTR-042"}))
    cursor = 0
    while not task.done():
        for event in db.all("SELECT * FROM events WHERE id>? ORDER BY id", (cursor,)):
            cursor = event["id"]
            payload = json.loads(event["payload"])
            print(f"{event['agent']}: {event['kind']} {payload.get('tool', '')}", flush=True)
        await asyncio.sleep(2)
    await task
    await runner.close()
    run = db.one("SELECT status,error,result FROM runs WHERE id=?", (run_id,))
    events = db.all("SELECT agent,kind,created_at FROM events WHERE run_id=? ORDER BY id", (run_id,))
    order = db.one("SELECT plan,window_id FROM work_orders WHERE run_id=?", (run_id,))
    result = json.loads(run["result"]) if run["result"] else {}
    evidence = result.get("evidence", {})
    expected = "escalated" if options.scenario == "stockout" else "completed"
    checks = {
        "expected_status": run["status"] == expected,
        "five_conclusions": sum(e["kind"] == "completed" for e in events) == 5,
        "six_tool_results": sum(e["kind"] == "tool_result" for e in events) == 6,
        "proposal_policy": order is None if options.scenario == "stockout" else order is not None,
    }
    # Check the actual constraint output, rather than trusting a model's claim.
    windows = evidence.get("evaluate_windows", {})
    selected = next(
        (w for w in windows.get("windows", []) if w["id"] == windows.get("selected_window_id")), None
    )
    checks["schedule_policy"] = (
        (selected is None)
        if options.scenario == "stockout"
        else bool(selected and selected["feasible"] and selected["production_fraction"] == 0.15)
    )
    agent_seconds = {}
    for event in events:
        if event["kind"] == "started":
            agent_seconds[event["agent"]] = datetime.fromisoformat(event["created_at"])
        elif event["kind"] == "completed" and event["agent"] in agent_seconds:
            agent_seconds[event["agent"]] = round(
                (datetime.fromisoformat(event["created_at"]) - agent_seconds[event["agent"]]).total_seconds(),
                2,
            )
    report = {
        "model": settings.nvidia_model,
        "thinking": settings.nvidia_enable_thinking,
        "max_tokens": settings.nvidia_max_tokens,
        "scenario": options.scenario,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "status": run["status"],
        "error": run["error"],
        "run_id": run_id,
        "agent_seconds": {k: v for k, v in agent_seconds.items() if isinstance(v, (float, int))},
        "rejected_tool_calls": sum(e["kind"] == "tool_error" for e in events),
        "provider_retries": sum(e["kind"] == "provider_retry" for e in events),
        "checks": checks,
        "passed": all(checks.values()),
    }
    path.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print(f"Validation database: {path}", flush=True)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
