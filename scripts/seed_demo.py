"""Opt-in synthetic inputs only. Never seeds runs, predictions, or AI outputs.

Run with: python -m scripts.seed_demo
This adds editable scenario inputs to the real database. All timestamps are
relative to invocation time and all telemetry sources identify themselves as
synthetic. Re-running adds fresh readings/windows but does not reset user data.
"""

import random
from datetime import datetime, timedelta, timezone

from backend.config import Settings
from backend.db import Database, audit, dump, uid


def seed(db):
    db.initialize()
    instant = datetime.now(timezone.utc)
    rng = random.Random(42)
    with db.transaction() as connection:
        for index, identifier in enumerate(("MTR-042", "MTR-611", "MTR-284", "PMP-117")):
            kind = "pump" if index == 3 else "motor"
            connection.execute(
                "INSERT OR IGNORE INTO assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    "Cooling water pump" if index == 3 else f"Conveyor drive {index + 1}",
                    "Packaging Line 3",
                    kind,
                    22 + index * 2,
                    0.8 - index * 0.05,
                    8,
                    9,
                    12000,
                    7,
                    90,
                    instant.isoformat(),
                ),
            )
            for step in range(36):
                vibration = 2.2 + step * 0.16 if index == 0 else 2.5 + rng.uniform(-0.2, 0.2)
                connection.execute(
                    "INSERT OR IGNORE INTO telemetry VALUES(?,?,?,?,?,?,?)",
                    (
                        uid(),
                        identifier,
                        (instant - timedelta(hours=35 - step)).isoformat(),
                        round(vibration, 2),
                        round(60 + vibration * 2, 2),
                        80,
                        "synthetic-demo",
                    ),
                )
        connection.execute(
            "INSERT OR IGNORE INTO parts(id,name,stock) VALUES('INSPECTION-KIT','Inspection consumables kit',10)"
        )
        for kind in ("motor", "pump", "fan", "drive"):
            connection.execute(
                "INSERT OR IGNORE INTO procedures VALUES(?,?,?,?,?,?,?)",
                (
                    f"INSPECT-{kind.upper()}",
                    kind,
                    "Inspect abnormal vibration and document findings",
                    2,
                    dump([{"part_id": "INSPECTION-KIT", "quantity": 1}]),
                    dump(
                        [
                            "Confirm site-approved procedure and permit with the responsible supervisor",
                            "Confirm required site energy-isolation controls with qualified personnel",
                            "Perform the authorized inspection and record measurements",
                            "Record findings and obtain site authorization before return to service",
                        ]
                    ),
                    "SYNTHETIC DEMO PROCEDURE — replace with a site-approved SOP before operational use",
                ),
            )
        for offset, duration, production, technicians, permit in (
            (3, 1, 0.1, 1, 1),
            (6, 3, 0.15, 1, 1),
            (12, 4, 0.8, 1, 1),
            (18, 3, 0.05, 0, 1),
        ):
            connection.execute(
                "INSERT INTO windows VALUES(?,?,?,?,?,?,?)",
                (
                    uid(),
                    "Packaging Line 3",
                    (instant + timedelta(hours=offset)).isoformat(),
                    (instant + timedelta(hours=offset + duration)).isoformat(),
                    production,
                    technicians,
                    permit,
                ),
            )
        audit(connection, "seed-script", "synthetic_inputs_added", "demo", {"source": "synthetic-demo"})


if __name__ == "__main__":
    seed(Database(Settings().readyline_db))
    print("Synthetic input records added. No AI results or work orders were seeded.")
