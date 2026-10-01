"""API-only deterministic reports for observe-only Kaizen."""

from collections import Counter
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.services.kaizen.store import DbKaizenStore, db_kaizen_store
from app.services.kaizen.types import (
    KAIZEN_REPORT_SCHEMA,
    KaizenConfig,
    as_utc,
    utc_iso,
)


def write_daily_report(
    db: Session,
    *,
    user_id: int,
    realm: str,
    config: KaizenConfig,
    now: datetime,
    store: DbKaizenStore = db_kaizen_store,
) -> dict[str, Any]:
    """Build and persist the current daily API-only report preview."""
    period_key, period_start, period_end = daily_period(now, config.report_timezone)
    observations = store.list_observations(
        db,
        user_id=user_id,
        realm=realm,
        since=period_start,
        until=as_utc(now),
        limit=1000,
    )
    payload = build_daily_report(
        realm=realm,
        period_key=period_key,
        period_start=period_start,
        period_end=period_end,
        observations=observations,
    )
    return store.save_report(
        db,
        user_id=user_id,
        realm=realm,
        kind="daily",
        period_key=period_key,
        period_start=period_start,
        period_end=period_end,
        payload=payload,
    )


def daily_period(now: datetime, timezone_name: str) -> tuple[str, datetime, datetime]:
    """Return the local calendar-day window as UTC timestamps."""
    try:
        report_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("kaizen_report_timezone is not valid") from exc
    local_now = as_utc(now).astimezone(report_timezone)
    local_start = datetime.combine(local_now.date(), time.min, tzinfo=report_timezone)
    local_end = datetime.combine(local_now.date(), time.max, tzinfo=report_timezone)
    return (
        local_now.date().isoformat(),
        local_start.astimezone(timezone.utc),
        local_end.astimezone(timezone.utc),
    )


def build_daily_report(
    *,
    realm: str,
    period_key: str,
    period_start: datetime,
    period_end: datetime,
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Render facts, freshness, and confidence without model interpretation."""
    latest = _latest_by_kpi_source(observations)
    state_counts = Counter(str(item.get("state") or "missing") for item in latest)
    return {
        "schema": KAIZEN_REPORT_SCHEMA,
        "kind": "daily",
        "realm": realm,
        "period_key": period_key,
        "period_start": utc_iso(period_start),
        "period_end": utc_iso(period_end),
        "mode": "observe_only",
        "delivery": "api_only",
        "summary": {
            "observation_count": len(observations),
            "latest_kpi_count": len(latest),
            "state_counts": dict(sorted(state_counts.items())),
        },
        "kpis": latest,
        "source_freshness": _source_freshness(latest),
        "automatic_actions": [],
        "candidates": [],
    }


def _latest_by_kpi_source(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for observation in observations:
        key = (
            str(observation.get("kpi_id") or ""),
            str(observation.get("source_tui") or ""),
        )
        timestamp = str(observation.get("observed_at") or "")
        if key not in latest or timestamp > str(latest[key].get("observed_at") or ""):
            latest[key] = observation
    return [latest[key] for key in sorted(latest)]


def _source_freshness(observations: list[dict[str, Any]]) -> dict[str, Any]:
    freshness = [
        item
        for item in observations
        if item.get("kpi_id") == "report_source_freshness_rate"
    ]
    values = [
        float(item["value_numeric"])
        for item in freshness
        if item.get("value_numeric") is not None
    ]
    return {
        "state": "missing"
        if not values
        else "healthy"
        if min(values) >= 1.0
        else "stale",
        "value": min(values) if values else None,
        "sources": len(values),
    }
