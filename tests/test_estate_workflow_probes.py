"""Ensure workflow observations preserve uncertainty and exclude business content."""

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "workflow", Path(__file__).parents[1] / "scripts/estate_workflow_probes.py"
)
probes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probes)
NOW = datetime(2026, 9, 15, 14, tzinfo=timezone.utc)


def test_earlybird_counts_attempts_without_exposing_content():
    state = {
        "run_history": [
            dict(
                finished_at=NOW.isoformat(),
                transcribed=2,
                whisper_errors=1,
                watch_signals=["private business text"],
            )
        ],
        "whisper_retries": {
            "private-file-id": dict(
                last_failed_at="2026-09-15T12:00:00Z", last_error="secret title"
            )
        },
        "whisper_remote_health": dict(checked_at=NOW.isoformat(), ready=True),
    }
    rows = probes.earlybird(state, NOW)
    values = {m["id"]: m["value"] for m in rows[0]["metrics"]}
    assert values["completion_rate"] == 2 / 3
    assert values["known_retry_records"] == 1
    assert values["oldest_retry_age"] == 7200
    assert "private" not in json.dumps(rows) and "secret" not in json.dumps(rows)
    assert rows[0]["level"] == "warn"


def test_no_success_is_unknown_and_failed_preflight_is_separate():
    rows = probes.earlybird(
        {
            "run_history": [
                dict(finished_at=NOW.isoformat(), transcribed=0, whisper_errors=0)
            ]
        },
        NOW,
    )
    values = {m["id"]: m["value"] for m in rows[0]["metrics"]}
    assert values["completion_rate"] is None
    assert values["last_success_age"] is None
    assert rows[1]["level"] == "bad"


def test_cached_site_inventory_keeps_its_original_timestamp():
    rows = probes.housebot(
        {
            "sites": [
                dict(
                    name="Beach",
                    checked_at=NOW.isoformat(),
                    level="warn",
                    inventory=dict(
                        source="last_good", last_good_checked_at="2026-09-06T00:00:00Z"
                    ),
                )
            ]
        },
        NOW,
    )
    assert rows[0]["metrics"][0]["source_timestamp"] == "2026-09-06T00:00:00Z"
    assert rows[0]["metrics"][1]["value"] is None
