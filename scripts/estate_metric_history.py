"""Retain source-dated KPI samples independently of collector availability."""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
import sqlite3

RETENTION_SECONDS = 7 * 86400
MAX_SAMPLES = 2016
DISPLAY_SAMPLES = 48


def attach_history(rows: list[dict], path: Path, now: dt.datetime) -> None:
    """Deduplicate source timestamps, isolate series, and attach recent real samples."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cutoff = now.timestamp() - RETENTION_SECONDS
    with sqlite3.connect(path, timeout=5) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS samples "
            "(series TEXT, stamp REAL, value REAL, PRIMARY KEY(series, stamp))"
        )
        db.execute("DELETE FROM samples WHERE stamp < ?", (cutoff,))
        for row in rows:
            for metric in row.get("metrics", []):
                series = json.dumps(
                    [
                        row.get("application"),
                        row.get("id"),
                        metric.get("id"),
                        metric.get("unit"),
                        row.get("environment"),
                    ]
                )
                value = metric.get("value")
                try:
                    stamp = dt.datetime.fromisoformat(
                        str(metric.get("source_timestamp")).replace("Z", "+00:00")
                    )
                    valid = (
                        stamp.tzinfo is not None
                        and cutoff <= stamp.timestamp() <= now.timestamp()
                        and isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and math.isfinite(value)
                    )
                except (ValueError, TypeError, OverflowError):
                    valid = False
                if valid:
                    db.execute(
                        "INSERT OR IGNORE INTO samples VALUES (?, ?, ?)",
                        (series, stamp.timestamp(), value),
                    )
                    db.execute(
                        "DELETE FROM samples WHERE series = ? AND stamp NOT IN "
                        "(SELECT stamp FROM samples WHERE series = ? ORDER BY stamp DESC LIMIT ?)",
                        (series, series, MAX_SAMPLES),
                    )
                samples = db.execute(
                    "SELECT stamp, value FROM samples WHERE series = ? "
                    "ORDER BY stamp DESC LIMIT ?",
                    (series, DISPLAY_SAMPLES),
                ).fetchall()
                metric["history"] = [
                    {
                        "observed_at": dt.datetime.fromtimestamp(
                            t, dt.timezone.utc
                        ).isoformat(),
                        "value": v,
                    }
                    for t, v in reversed(samples)
                ]
