"""Real source samples survive refresh failures without inventing trend points."""

import copy
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sqlite3

spec = importlib.util.spec_from_file_location(
    "history", Path(__file__).resolve().parents[1] / "scripts/estate_metric_history.py"
)
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)
NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


def row(value=0, stamp=NOW, environment="production"):
    return {
        "application": "example",
        "id": "source",
        "environment": environment,
        "metrics": [
            {
                "id": "completed",
                "value": value,
                "unit": "items",
                "source_timestamp": stamp.isoformat(),
            }
        ],
    }


def test_deduplicates_source_time_and_survives_unavailable_collection(tmp_path):
    path = tmp_path / "history.db"
    sample = row()
    history.attach_history([sample], path, NOW)
    history.attach_history([sample], path, NOW + timedelta(minutes=5))
    assert len(sample["metrics"][0]["history"]) == 1
    history.attach_history([], path, NOW + timedelta(minutes=6))
    later = row(3, NOW + timedelta(minutes=10))
    history.attach_history([later], path, NOW + timedelta(minutes=10))
    assert [p["value"] for p in later["metrics"][0]["history"]] == [0, 3]


def test_invalid_missing_and_future_values_are_not_history(tmp_path):
    for value in [None, "0", float("nan"), float("inf"), True]:
        sample = row(value)
        history.attach_history([sample], tmp_path / "invalid.db", NOW)
        assert sample["metrics"][0]["history"] == []
    sample = row(stamp=NOW + timedelta(seconds=1))
    history.attach_history([sample], tmp_path / "invalid.db", NOW)
    assert sample["metrics"][0]["history"] == []


def test_series_do_not_mix_environments_units_or_sources(tmp_path):
    path = tmp_path / "history.db"
    history.attach_history([row()], path, NOW)
    for field, value in [
        ("environment", "staging"),
        ("id", "other-source"),
        ("application", "other-app"),
    ]:
        sample = row(9)
        sample[field] = value
        history.attach_history([sample], path, NOW)
        assert [p["value"] for p in sample["metrics"][0]["history"]] == [9]
    sample = row(8)
    sample["metrics"][0]["unit"] = "seconds"
    history.attach_history([sample], path, NOW)
    assert [p["value"] for p in sample["metrics"][0]["history"]] == [8]


def test_retention_and_display_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "MAX_SAMPLES", 3)
    monkeypatch.setattr(history, "DISPLAY_SAMPLES", 2)
    path = tmp_path / "history.db"
    for offset in range(5):
        sample = row(offset, NOW + timedelta(minutes=offset))
        history.attach_history([sample], path, NOW + timedelta(minutes=offset))
    assert [p["value"] for p in sample["metrics"][0]["history"]] == [3, 4]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 3
    history.attach_history([], path, NOW + timedelta(days=8))
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 0
