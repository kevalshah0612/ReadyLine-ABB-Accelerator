"""Deterministic, inspectable tools used by the model-driven agents.

This is an engineering policy, not a trained failure-probability model. Numbers
are recomputed from stored measurements and constraints; the UI labels them as
condition/priority scores rather than unvalidated probabilities or RUL claims.
"""

import json
import math
from datetime import datetime, timedelta, timezone


class DomainError(ValueError):
    """A recoverable business constraint failure, safe to show to operators."""


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def condition(asset: dict, readings: list[dict]) -> dict:
    if len(readings) < 3:
        raise DomainError("At least three timestamped readings are required for analysis")
    readings = sorted(readings, key=lambda row: row["observed_at"])
    latest = readings[-1]
    age_hours = (datetime.now(timezone.utc) - parse_time(latest["observed_at"])).total_seconds() / 3600
    if age_hours > 24:
        raise DomainError("Latest telemetry is over 24 hours old; ingest a fresh reading first")
    origin = parse_time(readings[0]["observed_at"])
    xs = [(parse_time(r["observed_at"]) - origin).total_seconds() / 3600 for r in readings]
    ys = [r["vibration"] for r in readings]
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator < 0.0001:
        raise DomainError("Readings need distinct timestamps spanning at least a minute")
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
    vibration_ratio = latest["vibration"] / asset["vibration_limit"]
    temperature_ratio = max(0, latest["temperature"] / asset["temperature_limit"])
    crossing = max(0, (asset["vibration_limit"] - latest["vibration"]) / slope) if slope > 0 else None
    severity = min(1, max(vibration_ratio, temperature_ratio) / 1.5)
    # A bounded local policy sets the review deadline; it is NOT a failure horizon.
    hours = 24 if max(vibration_ratio, temperature_ratio) >= 1 else min(168, max(24, crossing or 168))
    deadline = datetime.now(timezone.utc) + timedelta(hours=hours)
    return {
        "latest": latest,
        "sample_count": len(readings),
        "span_hours": round(xs[-1], 2),
        "vibration_slope_per_hour": round(slope, 5),
        "vibration_ratio": round(vibration_ratio, 3),
        "temperature_ratio": round(temperature_ratio, 3),
        "condition_score": round(100 * severity),
        "threshold_crossing_hours": round(crossing, 2) if crossing is not None else None,
        "threshold_status": "already_exceeded" if vibration_ratio >= 1 else "below_limit",
        "threshold_note": "Zero crossing hours means the threshold is already reached, not a timestamp or data-quality error.",
        "review_deadline": deadline.isoformat(),
        "policy": "condition-v1",
        "limitations": "Linear threshold projection, not calibrated failure probability or remaining useful life.",
    }


def find_peers(db, asset: dict, limit: int = 5) -> dict:
    candidates = db.all(
        "SELECT * FROM assets WHERE id<>? AND equipment_class=?", (asset["id"], asset["equipment_class"])
    )
    peers = []
    for candidate in candidates:
        # Symmetric relative capacity difference and normalized duty-cycle distance.
        power = abs(asset["rated_power"] - candidate["rated_power"]) / max(
            asset["rated_power"], candidate["rated_power"]
        )
        duty = abs(asset["duty_cycle"] - candidate["duty_cycle"])
        distance = math.sqrt((0.65 * power**2) + (0.35 * duty**2))
        history = db.all(
            "SELECT id,feedback,completed_at FROM work_orders WHERE asset_id=? AND status='completed' "
            "ORDER BY completed_at DESC LIMIT 5",
            (candidate["id"],),
        )
        peers.append(
            {
                "asset_id": candidate["id"],
                "name": candidate["name"],
                "similarity": round(max(0, 1 - distance), 3),
                "confirmed_repairs": [{**h, "feedback": json.loads(h["feedback"])} for h in history],
            }
        )
    peers.sort(key=lambda item: (-item["similarity"], item["asset_id"]))
    selected = peers[:limit]
    own = db.all(
        "SELECT id,feedback,completed_at FROM work_orders WHERE asset_id=? AND status='completed' "
        "ORDER BY completed_at DESC LIMIT 5",
        (asset["id"],),
    )
    return {
        "peers": selected,
        "asset_history": [{**h, "feedback": json.loads(h["feedback"])} for h in own],
        "confirmed_peer_repairs": sum(len(p["confirmed_repairs"]) for p in selected),
        "method": "Same class; weighted normalized capacity and duty-cycle distance. Similarity is not diagnostic confidence.",
    }


def priority(asset: dict, health: dict, fleet: dict) -> dict:
    consequence = (0.45 * asset["safety"] + 0.55 * asset["production_impact"]) / 10
    score = round(min(100, max(0, health["condition_score"] * consequence)))
    return {
        "score": score,
        "level": "critical" if score >= 70 else "high" if score >= 45 else "monitor",
        "consequence": round(consequence, 3),
        "condition_score": health["condition_score"],
        "evidence_count": fleet["confirmed_peer_repairs"],
        "review_deadline": health["review_deadline"],
        "formula": "condition_score × (0.45 × safety + 0.55 × production_impact) / 10",
        "estimated_unplanned_hourly_cost": asset["hourly_cost"],
        "cost_note": "User-supplied hourly exposure; not measured savings.",
    }


def build_plan(db, asset: dict, procedure_id: str) -> dict:
    procedure = db.one(
        "SELECT * FROM procedures WHERE id=? AND equipment_class=?", (procedure_id, asset["equipment_class"])
    )
    if not procedure:
        raise DomainError("Select an existing procedure for this equipment class")
    procedure["parts"] = json.loads(procedure["parts"])
    procedure["steps"] = json.loads(procedure["steps"])
    availability = []
    for item in procedure["parts"]:
        part = db.one("SELECT * FROM parts WHERE id=?", (item["part_id"],))
        available = part["stock"] - part["reserved"] if part else 0
        availability.append(
            {
                **item,
                "name": part["name"] if part else item["part_id"],
                "available": available,
                "ready": available >= item["quantity"],
            }
        )
    return {
        "procedure": procedure,
        "parts": availability,
        "parts_ready": all(p["ready"] for p in availability),
        "approval_required": True,
    }


def rank_windows(db, asset: dict, plan: dict, deadline: str, exclude_order: str | None = None) -> dict:
    windows = db.all("SELECT * FROM windows WHERE area=? ORDER BY starts_at", (asset["area"],))
    # One maintenance crew per area: disallow overlapping reservations, even if
    # two different window records refer to overlapping clock times.
    reservations = db.all(
        "SELECT w.starts_at,w.ends_at,o.id FROM work_orders o JOIN windows w ON w.id=o.window_id "
        "WHERE w.area=? AND o.status='approved'",
        (asset["area"],),
    )
    evaluated = []
    duration = plan["procedure"]["duration_hours"]
    for window in windows:
        start, end = parse_time(window["starts_at"]), parse_time(window["ends_at"])
        reasons = []
        if start <= datetime.now(timezone.utc):
            reasons.append("Window has already started")
        if (end - start).total_seconds() / 3600 < duration:
            reasons.append("Insufficient contiguous time")
        if start + timedelta(hours=duration) > parse_time(deadline):
            reasons.append("Completion would exceed the policy review deadline")
        if not plan["parts_ready"]:
            reasons.append("Required parts unavailable")
        if window["technicians"] < 1:
            reasons.append("No technician capacity")
        if not window["permit_ready"]:
            reasons.append("Permit not ready")
        if any(
            r["id"] != exclude_order and start < parse_time(r["ends_at"]) and end > parse_time(r["starts_at"])
            for r in reservations
        ):
            reasons.append("Maintenance crew already reserved during this interval")
        cost = duration * window["production_fraction"] * asset["hourly_cost"]
        evaluated.append(
            {
                **window,
                "feasible": not reasons,
                "reasons": reasons,
                "estimated_disruption_cost": round(cost, 2),
            }
        )
    evaluated.sort(key=lambda w: (not w["feasible"], w["estimated_disruption_cost"], w["starts_at"]))
    feasible = [w for w in evaluated if w["feasible"]]
    return {
        "windows": evaluated,
        "selected_window_id": feasible[0]["id"] if feasible else None,
        "policy": "Reject infeasible windows, then minimize modeled production disruption; break ties by start time.",
    }


class ToolContext:
    """A run-scoped capability set: agents cannot query arbitrary SQL or other assets."""

    def __init__(self, db, asset_id: str):
        self.db = db
        self.asset = db.one("SELECT * FROM assets WHERE id=?", (asset_id,))
        if not self.asset:
            raise DomainError("Unknown asset")
        self.readings = list(
            reversed(
                db.all(
                    "SELECT * FROM telemetry WHERE asset_id=? ORDER BY observed_at DESC,id DESC LIMIT 500",
                    (asset_id,),
                )
            )
        )
        self.results = {}

    def execute(self, name: str, arguments: dict):
        if name == "inspect_telemetry":
            result = condition(self.asset, self.readings)
        elif name == "find_peer_evidence":
            result = find_peers(self.db, self.asset, arguments.get("limit", 5))
        elif name == "calculate_priority":
            result = priority(
                self.asset, self.results["inspect_telemetry"], self.results["find_peer_evidence"]
            )
        elif name == "list_procedures":
            result = {
                "procedures": self.db.all(
                    "SELECT id,title,duration_hours,source FROM procedures WHERE equipment_class=?",
                    (self.asset["equipment_class"],),
                )
            }
        elif name == "build_work_order":
            result = build_plan(self.db, self.asset, arguments["procedure_id"])
        elif name == "evaluate_windows":
            result = rank_windows(
                self.db,
                self.asset,
                self.results["build_work_order"],
                self.results["calculate_priority"]["review_deadline"],
            )
        else:
            raise DomainError("Tool not allowed")
        self.results[name] = result
        return result
