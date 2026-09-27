import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.db import dump, now, uid
from backend.domain import DomainError, ToolContext, condition, find_peers


def propose(client, asset_id="MTR-042"):
    """Build a deterministic proposal fixture, never used by production code."""
    db = client.app.state.db
    context = ToolContext(db, asset_id)
    for name in ("inspect_telemetry", "find_peer_evidence", "calculate_priority", "list_procedures"):
        context.execute(name, {})
    plan = context.execute("build_work_order", {"procedure_id": "INSPECT-MOTOR"})
    windows = context.execute("evaluate_windows", {})
    identifier, run_id = uid(), uid()
    with db.transaction() as c:
        actor = c.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
        c.execute(
            "INSERT INTO runs(id,asset_id,status,created_at,requested_by) VALUES(?,?,?,?,?)",
            (run_id, asset_id, "completed", now(), actor),
        )
        plan.update(
            priority=context.results["calculate_priority"],
            telemetry_id=context.results["inspect_telemetry"]["latest"]["id"],
            agent_summary="Test fixture",
        )
        c.execute(
            "INSERT INTO work_orders(id,run_id,asset_id,status,plan,window_id,created_at) VALUES(?,?,?,?,?,?,?)",
            (identifier, run_id, asset_id, "proposed", dump(plan), windows["selected_window_id"], now()),
        )
    return identifier


def completion():
    return {
        "finding": "Measured alignment issue confirmed during inspection",
        "actual_hours": 1.8,
        "post_vibration": 2.4,
        "completed_steps": [0, 1, 2, 3],
    }


def test_fresh_database_has_no_fabricated_assets_runs_or_predictions(client):
    assert client.get("/api/assets").json() == []
    assert client.get("/api/runs").json() == []
    assert client.get("/api/work-orders").json() == []


def test_auth_and_setup_are_enforced(client):
    assert (
        client.post("/api/auth/setup", json={"username": "other", "password": "another-password"}).status_code
        == 409
    )
    client.post("/api/auth/logout", json={})
    assert client.get("/api/assets").status_code == 401


def test_custom_header_required_for_mutations(client):
    response = client.post("/api/auth/logout", json={}, headers={"X-ReadyLine": "wrong"})
    assert response.status_code == 403


def test_health_uses_measurements_and_bounds_priority(seeded):
    ctx = ToolContext(seeded.app.state.db, "MTR-042")
    health = ctx.execute("inspect_telemetry", {})
    assert health["vibration_slope_per_hour"] == pytest.approx(0.16)
    assert health["threshold_status"] == "already_exceeded"
    ctx.execute("find_peer_evidence", {})
    risk = ctx.execute("calculate_priority", {})
    assert 0 <= risk["score"] <= 100
    assert "probability" not in risk
    ctx.readings[-1]["vibration"] = 500
    assert condition(ctx.asset, ctx.readings)["condition_score"] <= 100


def test_stale_and_insufficient_telemetry_rejected(seeded):
    ctx = ToolContext(seeded.app.state.db, "MTR-042")
    with pytest.raises(DomainError, match="three"):
        condition(ctx.asset, ctx.readings[:2])
    for r in ctx.readings:
        r["observed_at"] = (datetime.fromisoformat(r["observed_at"]) - timedelta(days=2)).isoformat()
    with pytest.raises(DomainError, match="24 hours"):
        condition(ctx.asset, ctx.readings)


def test_ingestion_is_idempotent_and_validates_time(seeded):
    reading = {"observed_at": now(), "vibration": 4, "temperature": 65, "load": 80, "source": "test-gateway"}
    path = "/api/assets/MTR-042/telemetry"
    assert seeded.post(path, json={"readings": [reading]}).json()["inserted"] == 1
    assert seeded.post(path, json={"readings": [reading]}).json()["inserted"] == 0
    reading["observed_at"] = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    assert seeded.post(path, json={"readings": [reading]}).status_code == 422
    reading["observed_at"] = "2026-01-01T12:00:00"
    assert seeded.post(path, json={"readings": [reading]}).status_code == 422


def test_window_constraints_are_evaluated_not_preset(seeded):
    ctx = ToolContext(seeded.app.state.db, "MTR-042")
    for name in ("inspect_telemetry", "find_peer_evidence", "calculate_priority"):
        ctx.execute(name, {})
    ctx.execute("build_work_order", {"procedure_id": "INSPECT-MOTOR"})
    result = ctx.execute("evaluate_windows", {})
    assert sum(w["feasible"] for w in result["windows"]) == 2
    winner = next(w for w in result["windows"] if w["id"] == result["selected_window_id"])
    assert winner["production_fraction"] == 0.15
    assert any("Insufficient contiguous time" in w["reasons"] for w in result["windows"])
    with seeded.app.state.db.transaction() as c:
        c.execute("UPDATE parts SET stock=0")
    ctx.execute("build_work_order", {"procedure_id": "INSPECT-MOTOR"})
    assert ctx.execute("evaluate_windows", {})["selected_window_id"] is None


def test_complete_requires_approval_and_all_steps(seeded):
    identifier = propose(seeded)
    path = f"/api/work-orders/{identifier}"
    assert seeded.post(path + "/complete", json=completion()).status_code == 409
    assert seeded.post(path + "/approve", json={}).status_code == 200
    assert seeded.post(path + "/approve", json={}).status_code == 409
    partial = completion()
    partial["completed_steps"] = [0, 1]
    assert seeded.post(path + "/complete", json=partial).status_code == 422
    partial["completed_steps"] = [0, 1, 2, 2, 3]
    assert seeded.post(path + "/complete", json=partial).status_code == 422
    part = seeded.get("/api/resources").json()["parts"][0]
    assert part["stock"] == 10 and part["reserved"] == 1
    assert seeded.post(path + "/complete", json=completion()).status_code == 200
    assert seeded.post(path + "/complete", json=completion()).status_code == 409
    part = seeded.get("/api/resources").json()["parts"][0]
    assert part["stock"] == 9 and part["reserved"] == 0
    order = seeded.get("/api/work-orders").json()[0]
    assert order["feedback"]["finding"] == completion()["finding"]
    db = seeded.app.state.db
    peers = find_peers(db, db.one("SELECT * FROM assets WHERE id='MTR-611'"))
    assert peers["confirmed_peer_repairs"] == 1


def test_approval_rechecks_telemetry_and_stock(seeded):
    identifier = propose(seeded)
    response = seeded.put(
        "/api/parts/INSPECTION-KIT", json={"id": "INSPECTION-KIT", "name": "Kit", "stock": 0}
    )
    assert response.status_code == 200
    assert seeded.post(f"/api/work-orders/{identifier}/approve", json={}).status_code == 409
    seeded.put("/api/parts/INSPECTION-KIT", json={"id": "INSPECTION-KIT", "name": "Kit", "stock": 10})
    seeded.post(
        "/api/assets/MTR-042/telemetry",
        json={
            "readings": [
                {"observed_at": now(), "vibration": 9, "temperature": 82, "load": 80, "source": "gateway"}
            ]
        },
    )
    response = seeded.post(f"/api/work-orders/{identifier}/approve", json={})
    assert response.status_code == 409 and "Telemetry changed" in response.text


def test_cancel_releases_reservation_exactly_once(seeded):
    identifier = propose(seeded)
    path = f"/api/work-orders/{identifier}"
    seeded.post(path + "/approve", json={})
    assert (
        seeded.put(
            "/api/parts/INSPECTION-KIT", json={"id": "INSPECTION-KIT", "name": "Kit", "stock": 0}
        ).status_code
        == 409
    )
    assert seeded.post(path + "/cancel", json={}).status_code == 200
    assert seeded.post(path + "/cancel", json={}).status_code == 409
    assert seeded.get("/api/resources").json()["parts"][0]["reserved"] == 0


def test_overlapping_reservations_cannot_both_be_approved(seeded):
    first = propose(seeded)
    second = propose(seeded, "MTR-611")
    assert seeded.post(f"/api/work-orders/{first}/approve", json={}).status_code == 200
    assert seeded.post(f"/api/work-orders/{second}/approve", json={}).status_code == 409


def test_role_checks_on_server(seeded):
    identifier = propose(seeded)
    credentials = {"username": "tech", "password": "technician-password-123"}
    assert seeded.post("/api/users", json={**credentials, "role": "technician"}).status_code == 201
    seeded.post("/api/auth/logout", json={})
    seeded.post("/api/auth/login", json=credentials)
    assert seeded.post(f"/api/work-orders/{identifier}/approve", json={}).status_code == 403
    assert seeded.post("/api/assets/MTR-042/runs", json={}).status_code == 403
    assert seeded.get("/api/assets").status_code == 200


def test_no_duplicate_active_analysis_or_open_order(seeded):
    assert seeded.post("/api/assets/MTR-042/runs", json={}).status_code == 202
    assert seeded.post("/api/assets/MTR-042/runs", json={}).status_code == 409
    propose(seeded, "MTR-611")
    assert seeded.post("/api/assets/MTR-611/runs", json={}).status_code == 409


def test_audit_is_persisted(seeded):
    identifier = propose(seeded)
    seeded.post(f"/api/work-orders/{identifier}/approve", json={})
    events = seeded.get("/api/audit").json()
    assert any(
        event["action"] == "work_order_approved" and event["entity_id"] == identifier for event in events
    )
    connection = seeded.app.state.db.connect()
    assert (
        json.loads(
            connection.execute("SELECT detail FROM audit WHERE action='work_order_approved'").fetchone()[0]
        )
        == {}
    )
    connection.close()


def test_approval_rejects_aged_telemetry_even_if_id_unchanged(seeded):
    identifier = propose(seeded)
    db = seeded.app.state.db
    # Shift every sample, preserving the ordering and identity used by the proposal.
    with db.transaction() as c:
        rows = c.execute("SELECT id,observed_at FROM telemetry WHERE asset_id='MTR-042'").fetchall()
        for row in rows:
            timestamp = datetime.fromisoformat(row["observed_at"]) - timedelta(days=2)
            c.execute("UPDATE telemetry SET observed_at=? WHERE id=?", (timestamp.isoformat(), row["id"]))
    response = seeded.post(f"/api/work-orders/{identifier}/approve", json={})
    assert response.status_code == 409 and "stale" in response.text


def test_missing_key_does_not_queue_fake_agent_run(seeded):
    from pydantic import SecretStr

    seeded.app.state.settings.nvidia_api_key = SecretStr("")
    assert seeded.post("/api/assets/MTR-042/runs", json={}).status_code == 503
    assert seeded.get("/api/runs").json() == []


def test_records_survive_app_restart_and_running_jobs_are_failed(seeded):
    from fastapi.testclient import TestClient
    from backend.main import create_app

    identifier = propose(seeded)
    db = seeded.app.state.db
    with db.transaction() as c:
        c.execute("UPDATE runs SET status='running' WHERE asset_id='MTR-042'")
    restarted = create_app(seeded.app.state.settings, start_worker=False)
    with TestClient(restarted, headers={"X-ReadyLine": "1"}) as fresh:
        fresh.post("/api/auth/login", json={"username": "operator", "password": "test-password-12345"})
        assert len(fresh.get("/api/assets").json()) == 4
        assert fresh.get("/api/work-orders").json()[0]["id"] == identifier
        assert fresh.get("/api/runs").json()[0]["status"] == "failed"
