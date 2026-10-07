"""Source timestamps and absent measurements remain distinct from fresh zeroes."""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "estate_workflow_probes_test",
    Path(__file__).resolve().parents[1] / "scripts/estate_workflow_probes.py",
)
probes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probes)
NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)


def test_timestamp_requires_source_timezone():
    assert probes.timestamp("2026-10-07T00:00:00") is None
    assert probes.timestamp(None) is None
    assert probes.timestamp("2026-10-07T00:00:00Z") == NOW


def test_earlybird_counts_only_retained_recent_history():
    recent = (NOW - timedelta(minutes=5)).isoformat()
    old = (NOW - timedelta(days=2)).isoformat()
    rows = probes.earlybird(
        {
            "run_history": [
                {"finished_at": recent, "transcribed": 3, "whisper_errors": 1},
                {"finished_at": old, "transcribed": 50},
            ],
            "whisper_retries": {"job": {"last_failed_at": recent}},
        },
        NOW,
    )
    metrics = {m["id"]: m for m in rows[0]["metrics"]}
    assert metrics["recordings_completed_24h"]["value"] == 3
    assert metrics["completion_rate"]["value"] == 0.75
    assert metrics["oldest_retry_age"]["value"] == 300
    assert metrics["recordings_completed_24h"]["source_timestamp"] == recent
    assert rows[1]["state"] == "unavailable"


def test_cached_housebot_inventory_keeps_its_original_age():
    old = (NOW - timedelta(hours=3)).isoformat()
    rows = probes.housebot(
        {
            "generated_at": NOW.isoformat(),
            "sites": [
                {
                    "name": "Home",
                    "inventory": {"source": "last_good", "last_good_checked_at": old},
                    "access": {"ok": True},
                }
            ],
        },
        NOW,
    )
    metrics = {m["id"]: m for m in rows[0]["metrics"]}
    assert metrics["inventory_age"]["value"] == 10800
    assert metrics["inventory_age"]["source_timestamp"] == old
    assert metrics["recent_device_warnings"]["value"] is None
