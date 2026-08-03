"""Deterministic daily-report tests for observe-only Kaizen."""

from datetime import datetime, timedelta, timezone

from app.services.kaizen.reports import daily_period, write_daily_report
from app.services.kaizen.store import DbKaizenStore
from app.services.kaizen.types import KaizenConfig
from tests.kaizen_helpers import create_kaizen_user, kpi_observation


def test_daily_period_uses_the_configured_local_calendar_day() -> None:
    now = datetime(2026, 8, 2, 5, 30, tzinfo=timezone.utc)

    period_key, start, end = daily_period(now, "America/Chicago")

    assert period_key == "2026-08-02"
    assert start == datetime(2026, 8, 2, 5, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 3, 4, 59, 59, 999999, tzinfo=timezone.utc)


def test_daily_report_uses_latest_values_and_freshness(db) -> None:
    store = DbKaizenStore()
    user = create_kaizen_user(db)
    now = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)
    observations = [
        kpi_observation(
            kpi_id="tui_queue_depth",
            observed_at=now - timedelta(minutes=5),
            value=2,
            state="warning",
        ),
        kpi_observation(kpi_id="tui_queue_depth", observed_at=now, value=0),
        kpi_observation(
            kpi_id="report_source_freshness_rate",
            observed_at=now,
            value=1,
        ),
        kpi_observation(
            kpi_id="tui_pending_seconds",
            observed_at=now + timedelta(minutes=1),
            value=99,
            state="warning",
        ),
    ]
    store.record_observations(db, user_id=user.id, observations=observations)

    report = write_daily_report(
        db,
        user_id=user.id,
        realm="personal/home",
        config=KaizenConfig(enabled=True, pilot_tui_ids=("pilot-1",)),
        now=now,
        store=store,
    )

    payload = report["payload"]
    queue_depth = next(
        item for item in payload["kpis"] if item["kpi_id"] == "tui_queue_depth"
    )
    assert payload["summary"] == {
        "observation_count": 3,
        "latest_kpi_count": 2,
        "state_counts": {"healthy": 2},
    }
    assert queue_depth["value_numeric"] == 0
    assert payload["source_freshness"] == {
        "state": "healthy",
        "value": 1.0,
        "sources": 1,
    }
    assert payload["automatic_actions"] == []
    assert payload["candidates"] == []
