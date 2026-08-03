"""Contract tests for sanitized Kaizen TUI snapshots."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.services.kaizen.types import TuiKpiSnapshot
from tests.kaizen_helpers import tui_snapshot_payload


def test_tui_snapshot_persists_only_the_fixed_aggregate_shape() -> None:
    observed_at = datetime(2026, 8, 2, 15, 30, tzinfo=timezone.utc)
    payload = tui_snapshot_payload(
        observed_at=observed_at,
        state_entered_at=observed_at,
        source_tui="pilot-safe",
    )

    snapshot = TuiKpiSnapshot.parse_obj(payload)
    sanitized = snapshot.sanitized_payload()

    assert set(sanitized) == {
        "schema",
        "realm",
        "source_tui",
        "observed_at",
        "state",
        "activity_state",
        "health_state",
        "prompt_visible",
        "waiting_visible",
        "state_entered_at",
        "metrics",
    }
    assert sanitized["observed_at"] == "2026-08-02T15:30:00+00:00"
    assert sanitized["state_entered_at"] == "2026-08-02T15:30:00+00:00"
    assert sanitized["schema"] == "norman.kaizen-tui-snapshot.v1"
    assert sanitized["metrics"] == {
        key: float(value) for key, value in payload["metrics"].items()
    }


@pytest.mark.parametrize(
    "path, value",
    [
        (("pane_text",), "private terminal transcript"),
        (("metrics", "unrecognized_metric"), 1),
    ],
)
def test_tui_snapshot_rejects_unapproved_payload_fields(
    path: tuple[str, ...], value: object
) -> None:
    payload = tui_snapshot_payload()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        TuiKpiSnapshot.parse_obj(payload)


def test_tui_snapshot_rejects_unknown_schema_versions() -> None:
    payload = tui_snapshot_payload(schema="norman.kaizen-tui-snapshot.v999")

    with pytest.raises(ValidationError):
        TuiKpiSnapshot.parse_obj(payload)
