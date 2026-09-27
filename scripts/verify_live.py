"""Run the production agent pipeline against NVIDIA using isolated synthetic inputs.

No canned provider responses. Leaves an auditable validation database in data/.
Requires NVIDIA_API_KEY in .env. Never prints credentials or reasoning tokens.
"""

import asyncio
import json
import secrets
from datetime import datetime, timezone

from backend.agents import NVIDIAAgentRunner, RunWorker
from backend.config import ROOT, Settings
from backend.db import Database, now, uid
from backend.security import password_hash
from scripts.seed_demo import seed


async def main():
    settings = Settings()
    if not settings.nvidia_api_key.get_secret_value():
        raise SystemExit("NVIDIA_API_KEY is missing")
    path = ROOT / "data" / f"validation-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.sqlite3"
    db = Database(str(path))
    seed(db)
    run_id, user_id = uid(), uid()
    with db.transaction() as connection:
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
    print(f"Starting real NVIDIA pipeline. Run: {run_id}", flush=True)
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
    run = db.one("SELECT status,error FROM runs WHERE id=?", (run_id,))
    print(json.dumps(run), flush=True)
    print(f"Validation database: {path}", flush=True)
    if run["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
