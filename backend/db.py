"""Small explicit SQLite repository. Every mutation uses a real transaction.

WAL lets the dashboard read while the worker writes. BEGIN IMMEDIATE serializes
approval, stock reservation, and job completion so concurrent clicks cannot
overbook a window or consume the same spare twice.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return uuid4().hex


def dump(value) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS users(
 id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('admin','supervisor','planner','technician')));
CREATE TABLE IF NOT EXISTS sessions(
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assets(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, area TEXT NOT NULL, equipment_class TEXT NOT NULL,
 rated_power REAL NOT NULL, duty_cycle REAL NOT NULL, safety INTEGER NOT NULL,
 production_impact INTEGER NOT NULL, hourly_cost REAL NOT NULL,
 vibration_limit REAL NOT NULL, temperature_limit REAL NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS telemetry(
 id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(id), observed_at TEXT NOT NULL,
 vibration REAL NOT NULL, temperature REAL NOT NULL, load REAL NOT NULL,
 source TEXT NOT NULL, UNIQUE(asset_id, observed_at, source));
CREATE INDEX IF NOT EXISTS idx_telemetry_asset_time ON telemetry(asset_id,observed_at);
CREATE TABLE IF NOT EXISTS parts(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, stock INTEGER NOT NULL CHECK(stock>=0),
 reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved>=0 AND reserved<=stock));
CREATE TABLE IF NOT EXISTS procedures(
 id TEXT PRIMARY KEY, equipment_class TEXT NOT NULL, title TEXT NOT NULL,
 duration_hours REAL NOT NULL, parts TEXT NOT NULL, steps TEXT NOT NULL, source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS windows(
 id TEXT PRIMARY KEY, area TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
 production_fraction REAL NOT NULL, technicians INTEGER NOT NULL, permit_ready INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_windows_area ON windows(area,starts_at);
CREATE TABLE IF NOT EXISTS runs(
 id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(id),
 status TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT, error TEXT,
 requested_by TEXT NOT NULL REFERENCES users(id), result TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_active ON runs(asset_id)
 WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS events(
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
 created_at TEXT NOT NULL, agent TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id,id);
CREATE TABLE IF NOT EXISTS work_orders(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
 asset_id TEXT NOT NULL REFERENCES assets(id), status TEXT NOT NULL,
 plan TEXT NOT NULL, window_id TEXT REFERENCES windows(id),
 created_at TEXT NOT NULL, approved_by TEXT REFERENCES users(id), approved_at TEXT,
 completed_by TEXT REFERENCES users(id), completed_at TEXT, feedback TEXT);
CREATE INDEX IF NOT EXISTS idx_work_asset_status ON work_orders(asset_id,status);
CREATE TABLE IF NOT EXISTS audit(
 id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, actor TEXT NOT NULL,
 action TEXT NOT NULL, entity_id TEXT NOT NULL, detail TEXT NOT NULL);
"""


class Database:
    def __init__(self, path: str):
        self.path = path

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def initialize(self):
        Path(self.path).resolve().parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as connection:
            connection.executescript(SCHEMA)
        connection = self.connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
        finally:
            connection.close()

    @contextmanager
    def transaction(self):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def all(self, sql: str, args=()):
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute(sql, args).fetchall()]
        finally:
            connection.close()

    def one(self, sql: str, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def event(self, run_id: str, agent: str, kind: str, payload: dict):
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO events(run_id,created_at,agent,kind,payload) VALUES(?,?,?,?,?)",
                (run_id, now(), agent, kind, dump(payload)),
            )


def audit(connection, actor: str, action: str, entity_id: str, detail=None):
    connection.execute(
        "INSERT INTO audit(created_at,actor,action,entity_id,detail) VALUES(?,?,?,?,?)",
        (now(), actor, action, entity_id, dump(detail or {})),
    )
