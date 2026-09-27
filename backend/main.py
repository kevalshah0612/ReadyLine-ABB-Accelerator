"""FastAPI application and explicit maintenance state transitions.

All domain mutations are authenticated, audited, and transactional. Agents only
propose work. Approval rechecks the world as it exists now, not the earlier LLM
snapshot. Only an approved job can be completed and added to fleet memory.
"""

import asyncio
import json
import secrets
import sqlite3
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.agents import NVIDIAAgentRunner, RunWorker
from backend.config import ROOT, Settings
from backend.db import Database, audit, dump, now, uid
from backend.domain import DomainError, build_plan, parse_time, rank_windows
from backend.schemas import (
    AssetInput,
    Credentials,
    FeedbackInput,
    NewUser,
    PartInput,
    ProcedureInput,
    TelemetryBatch,
    WindowInput,
)
from backend.security import current_user, password_hash, require, token_hash, verify_password


def decoded(row, *fields):
    if row is None:
        return None
    row = dict(row)
    for field in fields:
        if row.get(field):
            row[field] = json.loads(row[field])
    return row


def create_app(settings: Settings | None = None, runner_factory=None, start_worker=True):
    settings = settings or Settings()
    db = Database(settings.readyline_db)

    @asynccontextmanager
    async def lifespan(app):
        db.initialize()
        runner = runner_factory(settings, db) if runner_factory else NVIDIAAgentRunner(settings, db)
        worker = RunWorker(db, runner)
        app.state.worker = worker
        app.state.loop = asyncio.get_running_loop()
        with db.transaction() as connection:
            connection.execute(
                "UPDATE runs SET status='failed',error='Server restarted during analysis; start a new run',finished_at=? WHERE status='running'",
                (now(),),
            )
            connection.execute("DELETE FROM sessions WHERE expires<?", (now(),))
        task = asyncio.create_task(worker.serve()) if start_worker else None
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await runner.close()

    app = FastAPI(title="ReadyLine API", version="2.0.0", lifespan=lifespan)
    app.state.db, app.state.settings = db, settings
    app.state.login_attempts = {}

    @app.middleware("http")
    async def response_headers(request, call_next):
        # Same-origin JSON API; no permissive CORS. Public auth endpoints also
        # require the application header to reject cross-site form submissions.
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("X-ReadyLine") != "1":
                from fastapi.responses import JSONResponse

                return JSONResponse({"detail": "Missing request protection header"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
            )
        return response

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request, error):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            {"detail": "Conflicting record, duplicate ID, or invalid reference"}, status_code=409
        )

    @app.get("/api/status")
    def status():
        return {
            "service": "readyline",
            "database": "connected",
            "setup_required": not bool(db.one("SELECT id FROM users LIMIT 1")),
            "provider_configured": bool(settings.nvidia_api_key.get_secret_value()),
            "model": settings.nvidia_model,
            "telemetry_mode": "HTTP ingestion; no plant connector configured",
        }

    @app.post("/api/auth/setup", status_code=201)
    def setup(body: Credentials):
        # First-run bootstrap only. Run locally before exposing the service.
        with db.transaction() as connection:
            if connection.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise HTTPException(409, "Administrator already exists")
            user_id = uid()
            connection.execute(
                "INSERT INTO users VALUES(?,?,?,?)",
                (user_id, body.username, password_hash(body.password), "admin"),
            )
            audit(connection, user_id, "administrator_created", user_id)
        return {"message": "Administrator created. Sign in."}

    @app.post("/api/auth/login")
    def login(body: Credentials, request: Request, response: Response):
        # Small local-service throttle. Use a shared rate limiter behind a public gateway.
        host = request.client.host if request.client else "unknown"
        timestamp = datetime.now(timezone.utc).timestamp()
        attempts = [t for t in app.state.login_attempts.get(host, []) if timestamp - t < 60]
        app.state.login_attempts[host] = attempts
        if len(attempts) >= 10:
            raise HTTPException(429, "Too many sign-in attempts; wait one minute")
        attempts.append(timestamp)
        user = db.one("SELECT * FROM users WHERE username=?", (body.username,))
        if not user or not verify_password(body.password, user["password"]):
            raise HTTPException(401, "Incorrect username or password")
        token = secrets.token_urlsafe(32)
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO sessions VALUES(?,?,?)",
                (
                    token_hash(token),
                    user["id"],
                    (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(),
                ),
            )
        response.set_cookie(
            "readyline_session",
            token,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            max_age=43200,
        )
        return {key: user[key] for key in ("id", "username", "role")}

    @app.get("/api/auth/me")
    def me(user=Depends(current_user)):
        return user

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, user=Depends(current_user)):
        with db.transaction() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (token_hash(request.cookies.get("readyline_session", "")),),
            )
        response.delete_cookie("readyline_session")
        return {"message": "Signed out"}

    @app.post("/api/users", status_code=201)
    def create_user(body: NewUser, user=Depends(current_user)):
        require(user)
        identifier = uid()
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO users VALUES(?,?,?,?)",
                (identifier, body.username, password_hash(body.password), body.role),
            )
            audit(connection, user["id"], "user_created", identifier, {"role": body.role})
        return {"id": identifier, "username": body.username, "role": body.role}

    @app.get("/api/assets")
    def assets(user=Depends(current_user)):
        rows = db.all("SELECT * FROM assets ORDER BY id")
        for row in rows:
            row["latest"] = db.one(
                "SELECT * FROM telemetry WHERE asset_id=? ORDER BY observed_at DESC,id DESC LIMIT 1",
                (row["id"],),
            )
            row["latest_run"] = decoded(
                db.one("SELECT * FROM runs WHERE asset_id=? ORDER BY created_at DESC LIMIT 1", (row["id"],)),
                "result",
            )
        return rows

    @app.post("/api/assets", status_code=201)
    def create_asset(body: AssetInput, user=Depends(current_user)):
        require(user, "planner", "supervisor")
        values = body.model_dump()
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO assets(id,name,area,equipment_class,rated_power,duty_cycle,safety,production_impact,hourly_cost,vibration_limit,temperature_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (*values.values(), now()),
            )
            audit(connection, user["id"], "asset_created", body.id, values)
        return values

    @app.get("/api/assets/{asset_id}/telemetry")
    def telemetry(asset_id: str, user=Depends(current_user)):
        return list(
            reversed(
                db.all(
                    "SELECT * FROM telemetry WHERE asset_id=? ORDER BY observed_at DESC,id DESC LIMIT 500",
                    (asset_id,),
                )
            )
        )

    def queue_run(connection, asset_id, actor):
        if not settings.nvidia_api_key.get_secret_value():
            raise HTTPException(503, "Set NVIDIA_API_KEY in .env and restart the backend")
        if not connection.execute("SELECT 1 FROM assets WHERE id=?", (asset_id,)).fetchone():
            raise HTTPException(404, "Asset not found")
        if connection.execute(
            "SELECT 1 FROM work_orders WHERE asset_id=? AND status IN ('proposed','approved')", (asset_id,)
        ).fetchone():
            raise HTTPException(409, "Resolve or cancel this asset's open work order before a new analysis")
        identifier = uid()
        connection.execute(
            "INSERT INTO runs(id,asset_id,status,created_at,requested_by) VALUES(?,?,?,?,?)",
            (identifier, asset_id, "queued", now(), actor),
        )
        audit(connection, actor, "analysis_queued", identifier, {"asset_id": asset_id})
        return identifier

    @app.post("/api/assets/{asset_id}/telemetry", status_code=201)
    def ingest(asset_id: str, body: TelemetryBatch, user=Depends(current_user)):
        require(user, "planner", "supervisor")
        run_id, inserted = None, 0
        with db.transaction() as connection:
            if not connection.execute("SELECT 1 FROM assets WHERE id=?", (asset_id,)).fetchone():
                raise HTTPException(404, "Asset not found")
            for reading in body.readings:
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO telemetry VALUES(?,?,?,?,?,?,?)",
                    (
                        uid(),
                        asset_id,
                        reading.observed_at.isoformat(),
                        reading.vibration,
                        reading.temperature,
                        reading.load,
                        reading.source,
                    ),
                )
                inserted += cursor.rowcount
            if body.analyze:
                run_id = queue_run(connection, asset_id, user["id"])
            audit(connection, user["id"], "telemetry_ingested", asset_id, {"inserted": inserted})
        app.state.loop.call_soon_threadsafe(app.state.worker.wake.set)
        return {"inserted": inserted, "run_id": run_id}

    @app.post("/api/assets/{asset_id}/runs", status_code=202)
    def analyze(asset_id: str, user=Depends(current_user)):
        require(user, "planner", "supervisor")
        with db.transaction() as connection:
            identifier = queue_run(connection, asset_id, user["id"])
        app.state.loop.call_soon_threadsafe(app.state.worker.wake.set)
        return {"id": identifier, "status": "queued"}

    @app.get("/api/runs")
    def runs(user=Depends(current_user)):
        return [
            decoded(row, "result") for row in db.all("SELECT * FROM runs ORDER BY created_at DESC LIMIT 100")
        ]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, user=Depends(current_user)):
        row = decoded(db.one("SELECT * FROM runs WHERE id=?", (run_id,)), "result")
        if not row:
            raise HTTPException(404, "Run not found")
        return row

    @app.get("/api/runs/{run_id}/events")
    def events(run_id: str, user=Depends(current_user)):
        return [
            decoded(row, "payload")
            for row in db.all("SELECT * FROM events WHERE run_id=? ORDER BY id", (run_id,))
        ]

    @app.get("/api/runs/{run_id}/stream")
    async def stream_events(run_id: str, request: Request, user=Depends(current_user)):
        if not db.one("SELECT 1 FROM runs WHERE id=?", (run_id,)):
            raise HTTPException(404, "Run not found")
        try:
            cursor = max(0, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            cursor = 0

        async def generate():
            nonlocal cursor
            while not await request.is_disconnected():
                rows = db.all("SELECT * FROM events WHERE run_id=? AND id>? ORDER BY id", (run_id, cursor))
                for row in rows:
                    cursor = row["id"]
                    yield f"id: {cursor}\ndata: {dump(decoded(row, 'payload'))}\n\n"
                run = db.one("SELECT status FROM runs WHERE id=?", (run_id,))
                if run["status"] not in ("queued", "running"):
                    yield "event: done\ndata: {}\n\n"
                    break
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            generate(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    @app.get("/api/resources")
    def resources(user=Depends(current_user)):
        return {
            "parts": db.all("SELECT * FROM parts ORDER BY name"),
            "procedures": [
                decoded(row, "parts", "steps") for row in db.all("SELECT * FROM procedures ORDER BY title")
            ],
            "windows": db.all("SELECT * FROM windows ORDER BY starts_at"),
        }

    @app.put("/api/parts/{part_id}")
    def save_part(part_id: str, body: PartInput, user=Depends(current_user)):
        require(user, "planner", "supervisor")
        if part_id != body.id:
            raise HTTPException(422, "Path and part ID differ")
        with db.transaction() as connection:
            old = connection.execute("SELECT reserved FROM parts WHERE id=?", (part_id,)).fetchone()
            if old and body.stock < old["reserved"]:
                raise HTTPException(409, "Stock cannot be less than already reserved quantity")
            connection.execute(
                "INSERT INTO parts(id,name,stock) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,stock=excluded.stock",
                (body.id, body.name, body.stock),
            )
            audit(connection, user["id"], "inventory_updated", part_id, body.model_dump())
        return body

    @app.put("/api/procedures/{procedure_id}")
    def save_procedure(procedure_id: str, body: ProcedureInput, user=Depends(current_user)):
        require(user, "supervisor")
        if procedure_id != body.id:
            raise HTTPException(422, "Path and procedure ID differ")
        with db.transaction() as connection:
            for part in body.parts:
                if not connection.execute("SELECT 1 FROM parts WHERE id=?", (part.part_id,)).fetchone():
                    raise HTTPException(422, f"Unknown part: {part.part_id}")
            connection.execute(
                "INSERT INTO procedures VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET equipment_class=excluded.equipment_class,title=excluded.title,duration_hours=excluded.duration_hours,parts=excluded.parts,steps=excluded.steps,source=excluded.source",
                (
                    body.id,
                    body.equipment_class,
                    body.title,
                    body.duration_hours,
                    dump([p.model_dump() for p in body.parts]),
                    dump(body.steps),
                    body.source,
                ),
            )
            audit(connection, user["id"], "procedure_updated", body.id, body.model_dump())
        return body

    @app.post("/api/windows", status_code=201)
    def create_window(body: WindowInput, user=Depends(current_user)):
        require(user, "planner", "supervisor")
        identifier = uid()
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO windows VALUES(?,?,?,?,?,?,?)",
                (
                    identifier,
                    body.area,
                    body.starts_at.isoformat(),
                    body.ends_at.isoformat(),
                    body.production_fraction,
                    body.technicians,
                    int(body.permit_ready),
                ),
            )
            audit(connection, user["id"], "window_created", identifier, body.model_dump(mode="json"))
        return {"id": identifier, **body.model_dump(mode="json")}

    @app.delete("/api/windows/{window_id}")
    def remove_window(window_id: str, user=Depends(current_user)):
        require(user, "planner", "supervisor")
        with db.transaction() as connection:
            if connection.execute("SELECT 1 FROM work_orders WHERE window_id=?", (window_id,)).fetchone():
                raise HTTPException(
                    409, "This window is referenced by a work order and must be retained for audit"
                )
            connection.execute("DELETE FROM windows WHERE id=?", (window_id,))
            audit(connection, user["id"], "window_removed", window_id)
        return {"message": "Window removed"}

    @app.get("/api/work-orders")
    def work_orders(user=Depends(current_user)):
        return [
            decoded(row, "plan", "feedback")
            for row in db.all("SELECT * FROM work_orders ORDER BY created_at DESC LIMIT 200")
        ]

    @app.post("/api/work-orders/{order_id}/approve")
    def approve(order_id: str, user=Depends(current_user)):
        require(user, "supervisor")
        with db.transaction() as connection:
            order = decoded(
                connection.execute("SELECT * FROM work_orders WHERE id=?", (order_id,)).fetchone(), "plan"
            )
            if not order or order["status"] != "proposed":
                raise HTTPException(409, "Only a proposed work order can be approved")
            latest = connection.execute(
                "SELECT id,observed_at FROM telemetry WHERE asset_id=? ORDER BY observed_at DESC,id DESC LIMIT 1",
                (order["asset_id"],),
            ).fetchone()
            if not latest or latest["id"] != order["plan"]["telemetry_id"]:
                raise HTTPException(
                    409, "Telemetry changed since analysis. Cancel this proposal and analyze again."
                )
            if datetime.now(timezone.utc) - parse_time(latest["observed_at"]) > timedelta(hours=24):
                raise HTTPException(409, "Telemetry is now stale. Ingest fresh readings and analyze again.")
            asset = dict(
                connection.execute("SELECT * FROM assets WHERE id=?", (order["asset_id"],)).fetchone()
            )
            try:
                fresh_plan = build_plan(db, asset, order["plan"]["procedure"]["id"])
            except DomainError as error:
                raise HTTPException(409, str(error)) from error
            if fresh_plan["procedure"] != order["plan"]["procedure"]:
                raise HTTPException(409, "Procedure changed since analysis. Cancel and analyze again.")
            ranking = rank_windows(db, asset, fresh_plan, order["plan"]["priority"]["review_deadline"])
            candidate = next((w for w in ranking["windows"] if w["id"] == order["window_id"]), None)
            if not candidate or not candidate["feasible"]:
                raise HTTPException(
                    409,
                    {
                        "message": "The proposed window is no longer feasible",
                        "reasons": candidate["reasons"] if candidate else ["Missing window"],
                    },
                )
            for part in fresh_plan["parts"]:
                cursor = connection.execute(
                    "UPDATE parts SET reserved=reserved+? WHERE id=? AND stock-reserved>=?",
                    (part["quantity"], part["part_id"], part["quantity"]),
                )
                if cursor.rowcount != 1:
                    raise HTTPException(409, "Inventory changed; approval aborted")
            connection.execute(
                "UPDATE work_orders SET status='approved',approved_by=?,approved_at=? WHERE id=?",
                (user["id"], now(), order_id),
            )
            audit(connection, user["id"], "work_order_approved", order_id)
        return {"status": "approved"}

    @app.post("/api/work-orders/{order_id}/cancel")
    def cancel(order_id: str, user=Depends(current_user)):
        require(user, "supervisor")
        with db.transaction() as connection:
            order = decoded(
                connection.execute("SELECT * FROM work_orders WHERE id=?", (order_id,)).fetchone(), "plan"
            )
            if not order or order["status"] not in ("proposed", "approved"):
                raise HTTPException(409, "Only open work orders can be cancelled")
            if order["status"] == "approved":
                for part in order["plan"]["parts"]:
                    connection.execute(
                        "UPDATE parts SET reserved=reserved-? WHERE id=?", (part["quantity"], part["part_id"])
                    )
            connection.execute("UPDATE work_orders SET status='cancelled' WHERE id=?", (order_id,))
            audit(connection, user["id"], "work_order_cancelled", order_id)
        return {"status": "cancelled"}

    @app.post("/api/work-orders/{order_id}/complete")
    def complete(order_id: str, body: FeedbackInput, user=Depends(current_user)):
        require(user, "technician")
        with db.transaction() as connection:
            order = decoded(
                connection.execute("SELECT * FROM work_orders WHERE id=?", (order_id,)).fetchone(), "plan"
            )
            if not order or order["status"] != "approved":
                raise HTTPException(409, "Only an approved work order can be completed")
            expected = list(range(len(order["plan"]["procedure"]["steps"])))
            if sorted(body.completed_steps) != expected:
                raise HTTPException(422, "Complete every procedure step exactly once")
            for part in order["plan"]["parts"]:
                connection.execute(
                    "UPDATE parts SET stock=stock-?,reserved=reserved-? WHERE id=?",
                    (part["quantity"], part["quantity"], part["part_id"]),
                )
            connection.execute(
                "UPDATE work_orders SET status='completed',completed_by=?,completed_at=?,feedback=? WHERE id=?",
                (user["id"], now(), dump(body.model_dump()), order_id),
            )
            audit(connection, user["id"], "repair_feedback_recorded", order_id, body.model_dump())
        return {
            "status": "completed",
            "message": "Feedback saved and available to future fleet evidence retrieval",
        }

    @app.get("/api/audit")
    def audit_log(user=Depends(current_user)):
        return [decoded(row, "detail") for row in db.all("SELECT * FROM audit ORDER BY id DESC LIMIT 200")]

    frontend = ROOT / "frontend" / "dist"
    if (frontend / "assets").exists():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="static")

    @app.get("/")
    def index():
        if (frontend / "index.html").exists():
            return FileResponse(frontend / "index.html")
        return {"message": "Build the frontend: cd frontend && npm install && npm run build", "docs": "/docs"}

    return app


app = create_app()
