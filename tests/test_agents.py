"""Provider contract tests use synthetic stream fragments, never network access.

Live provider verification is separate: python -m scripts.verify_live.
"""

import asyncio
import json
from types import SimpleNamespace as NS

from backend.agents import NVIDIAAgentRunner, RunWorker
from backend.db import now, uid


class Stream:
    def __init__(self, chunks):
        self.chunks = chunks

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.chunks:
            raise StopAsyncIteration
        return self.chunks.pop(0)

    async def close(self):
        pass


class ToolCallingProvider:
    """Exercises argument-fragment assembly and tool round trips in the real runner."""

    def __init__(self):
        self.chat = NS(completions=NS(create=self.create))
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        offered = [
            tool["function"]["name"]
            for tool in kwargs["tools"]
            if tool["function"]["name"] != "submit_analysis"
        ]
        already = [call["function"]["name"] for m in kwargs["messages"] for call in m.get("tool_calls", [])]
        name = next((name for name in offered if name not in already), "submit_analysis")
        arguments = {}
        if name == "build_work_order":
            arguments = {"procedure_id": "INSPECT-MOTOR"}
        elif name == "submit_analysis":
            arguments = {
                "summary": "Test provider reviewed returned tool evidence.",
                "observations": ["Evidence retrieved"],
                "disposition": "proceed",
                "uncertainty": "Synthetic test data only",
            }
        encoded = json.dumps(arguments)
        chunks = []
        for index, fragment in enumerate((encoded[: len(encoded) // 2], encoded[len(encoded) // 2 :])):
            delta = NS(
                content=None,
                tool_calls=[
                    NS(
                        index=0,
                        id="call-test" if index == 0 else None,
                        function=NS(name=name if index == 0 else None, arguments=fragment),
                    )
                ],
            )
            chunks.append(NS(choices=[NS(delta=delta, finish_reason=None)]))
        chunks.append(NS(choices=[NS(delta=NS(content=None, tool_calls=None), finish_reason="tool_calls")]))
        return Stream(chunks)

    async def close(self):
        pass


def test_full_pipeline_records_actual_tools_and_proposal(seeded):
    db = seeded.app.state.db
    provider = ToolCallingProvider()
    runner = NVIDIAAgentRunner(seeded.app.state.settings, db, client=provider)
    run_id = uid()
    with db.transaction() as c:
        actor = c.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
        c.execute(
            "INSERT INTO runs(id,asset_id,status,created_at,requested_by) VALUES(?,?,?,?,?)",
            (run_id, "MTR-042", "running", now(), actor),
        )
    asyncio.run(RunWorker(db, runner).execute({"id": run_id, "asset_id": "MTR-042"}))
    assert db.one("SELECT status FROM runs WHERE id=?", (run_id,))["status"] == "completed"
    events = db.all("SELECT * FROM events WHERE run_id=?", (run_id,))
    assert len([e for e in events if e["kind"] == "completed"]) == 5
    assert len([e for e in events if e["kind"] == "tool_result"]) == 6
    assert db.one("SELECT status FROM work_orders WHERE run_id=?", (run_id,))["status"] == "proposed"
    assert all(r["stream"] for r in provider.requests)
    assert all(r["model"] == "nvidia/nemotron-3-ultra-550b-a55b" for r in provider.requests)


def test_provider_failure_never_becomes_fake_success(seeded):
    class BrokenProvider(ToolCallingProvider):
        async def create(self, **kwargs):
            raise RuntimeError("Test provider intentionally failed")

    db = seeded.app.state.db
    run_id = uid()
    with db.transaction() as c:
        actor = c.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
        c.execute(
            "INSERT INTO runs(id,asset_id,status,created_at,requested_by) VALUES(?,?,?,?,?)",
            (run_id, "MTR-042", "running", now(), actor),
        )
    runner = NVIDIAAgentRunner(seeded.app.state.settings, db, client=BrokenProvider())
    asyncio.run(RunWorker(db, runner).execute({"id": run_id, "asset_id": "MTR-042"}))
    assert db.one("SELECT status FROM runs WHERE id=?", (run_id,))["status"] == "failed"
    assert db.one("SELECT id FROM work_orders WHERE run_id=?", (run_id,)) is None
