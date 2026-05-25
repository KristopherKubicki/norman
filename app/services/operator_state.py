from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.orm import Session

from app import models
from app.schemas.operator_state import OperatorSourceSnapshot, OperatorStateOut

HOME_PRESENCE_TTL_SECONDS = 60 * 60 * 24
OFFICE_PRESENCE_TTL_SECONDS = 60 * 10
WORKSTATION_TTL_SECONDS = 60 * 10
WORKSTATION_ACTIVE_IDLE_THRESHOLD_SECONDS = 90
OFFICE_ZONE_TOKENS = {"office", "desk", "workspace", "study"}
HOME_PRESENT_VALUES = {
    "present",
    "home",
    "arrived",
    "active",
    "occupied",
    "open",
    "on",
}
HOME_ABSENT_VALUES = {
    "not present",
    "away",
    "departed",
    "inactive",
    "clear",
    "closed",
    "off",
    "absent",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _boolish(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    lowered = _lower(value)
    if not lowered:
        return None
    if lowered in {"1", "true", "yes", "y", "on", "active", "awake", "open"}:
        return True
    if lowered in {"0", "false", "no", "n", "off", "idle", "inactive", "locked"}:
        return False
    return None


def _intish(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _age_seconds(observed_at: Optional[datetime], *, now: datetime) -> Optional[int]:
    ts = _aware(observed_at)
    if ts is None:
        return None
    return max(0, int((now - ts).total_seconds()))


def _is_fresh(
    observed_at: Optional[datetime], *, ttl_seconds: int, now: datetime
) -> bool:
    age = _age_seconds(observed_at, now=now)
    return age is not None and age <= ttl_seconds


def _officeish(*parts: Any) -> bool:
    haystack = " ".join(_lower(part) for part in parts if _clean(part))
    return any(token in haystack for token in OFFICE_ZONE_TOKENS)


def _presence_value(value: Any) -> Optional[bool]:
    lowered = _lower(value)
    if not lowered:
        return None
    if lowered in HOME_PRESENT_VALUES:
        return True
    if lowered in HOME_ABSENT_VALUES:
        return False
    return None


def _presence_status(value: Optional[bool], *, fresh: bool) -> str:
    if not fresh:
        return "stale"
    if value is True:
        return "present"
    if value is False:
        return "away"
    return "unknown"


def _home_presence_snapshot(
    normalized: Dict[str, Any],
    observed_at: Optional[datetime],
    *,
    now: datetime,
) -> Optional[OperatorSourceSnapshot]:
    attribute = _lower(normalized.get("attribute"))
    device = _clean(normalized.get("device"))
    value = normalized.get("value")
    if attribute != "presence" and "presence" not in _lower(device):
        return None
    present = _presence_value(value)
    fresh = _is_fresh(observed_at, ttl_seconds=HOME_PRESENCE_TTL_SECONDS, now=now)
    return OperatorSourceSnapshot(
        kind="home_presence",
        source="hubitat",
        label=device or "Home presence",
        status=_presence_status(present, fresh=fresh),
        fresh=fresh,
        observed_at=_aware(observed_at),
        age_seconds=_age_seconds(observed_at, now=now),
        device=device or None,
        attribute=attribute or None,
        value=_clean(value) or None,
        details={"present": present, "location": normalized.get("location")},
    )


def _office_presence_snapshot(
    normalized: Dict[str, Any],
    observed_at: Optional[datetime],
    *,
    now: datetime,
) -> Optional[OperatorSourceSnapshot]:
    device = _clean(normalized.get("device"))
    attribute = _lower(normalized.get("attribute"))
    value = normalized.get("value")
    text = _clean(normalized.get("text") or normalized.get("text_summary"))
    if not _officeish(device, text, normalized.get("location"), normalized.get("zone")):
        return None
    if attribute not in {
        "presence",
        "motion",
        "occupancy",
        "contact",
    } and "presence" not in _lower(device):
        return None
    present = _presence_value(value)
    if present is None and attribute == "motion":
        lowered = _lower(value)
        if lowered == "active":
            present = True
        elif lowered == "inactive":
            present = False
    fresh = _is_fresh(observed_at, ttl_seconds=OFFICE_PRESENCE_TTL_SECONDS, now=now)
    return OperatorSourceSnapshot(
        kind="office_presence",
        source="hubitat",
        label=device or "Office presence",
        status=_presence_status(present, fresh=fresh),
        fresh=fresh,
        observed_at=_aware(observed_at),
        age_seconds=_age_seconds(observed_at, now=now),
        device=device or None,
        attribute=attribute or None,
        value=_clean(value) or None,
        details={"present": present, "location": normalized.get("location")},
    )


def _workstation_snapshot(
    normalized: Dict[str, Any],
    observed_at: Optional[datetime],
    *,
    now: datetime,
) -> OperatorSourceSnapshot:
    host = _clean(normalized.get("host"))
    zone = _clean(normalized.get("zone"))
    user_active = _boolish(normalized.get("user_active"))
    screen_awake = _boolish(normalized.get("screen_awake"))
    session_locked = _boolish(normalized.get("session_locked"))
    display_idle_seconds = _intish(normalized.get("display_idle_seconds"))
    if (
        user_active is None
        and screen_awake is not None
        and display_idle_seconds is not None
    ):
        user_active = bool(
            screen_awake
            and display_idle_seconds < WORKSTATION_ACTIVE_IDLE_THRESHOLD_SECONDS
        )
    fresh = _is_fresh(observed_at, ttl_seconds=WORKSTATION_TTL_SECONDS, now=now)
    if not fresh:
        status = "stale"
    elif session_locked:
        status = "locked"
    elif user_active:
        status = "active"
    elif screen_awake is False:
        status = "sleeping"
    else:
        status = "idle"
    return OperatorSourceSnapshot(
        kind="workstation_activity",
        source="activity_monitor",
        label=host or "Workstation",
        status=status,
        fresh=fresh,
        observed_at=_aware(observed_at),
        age_seconds=_age_seconds(observed_at, now=now),
        device=host or None,
        details={
            "zone": zone or None,
            "user_active": user_active,
            "screen_awake": screen_awake,
            "session_locked": session_locked,
            "display_idle_seconds": display_idle_seconds,
        },
    )


def _confidence_for(sources: Iterable[OperatorSourceSnapshot]) -> str:
    fresh_count = sum(1 for item in sources if item.fresh)
    if fresh_count >= 3:
        return "high"
    if fresh_count >= 2:
        return "medium"
    if fresh_count >= 1:
        return "low"
    return "unknown"


def build_operator_state(
    db: Session,
    *,
    user_id: int,
    limit: int = 500,
) -> OperatorStateOut:
    now = _utcnow()
    rows = (
        db.query(models.RoutingJob, models.RoutingEvent, models.Connector)
        .join(models.RoutingEvent, models.RoutingJob.event_id == models.RoutingEvent.id)
        .outerjoin(
            models.Connector, models.RoutingEvent.connector_id == models.Connector.id
        )
        .filter(models.RoutingEvent.user_id == user_id)
        .order_by(models.RoutingJob.id.desc())
        .limit(limit)
        .all()
    )

    home_presence: Optional[OperatorSourceSnapshot] = None
    office_presence: Optional[OperatorSourceSnapshot] = None
    workstation: Optional[OperatorSourceSnapshot] = None

    for job, event, _connector in rows:
        normalized = job.normalized if isinstance(job.normalized, dict) else {}
        if not normalized:
            continue
        passive_source = _lower(
            normalized.get("passive_source") or normalized.get("sensor_type")
        )
        observed_at = _aware(job.created_at or event.created_at)
        if passive_source == "hubitat":
            if home_presence is None:
                home_presence = _home_presence_snapshot(
                    normalized, observed_at, now=now
                )
            if office_presence is None:
                office_presence = _office_presence_snapshot(
                    normalized, observed_at, now=now
                )
        elif passive_source == "activity_monitor" and workstation is None:
            workstation = _workstation_snapshot(normalized, observed_at, now=now)
        if (
            home_presence is not None
            and office_presence is not None
            and workstation is not None
        ):
            break

    sources = [item for item in (home_presence, office_presence, workstation) if item]
    home_present = home_presence.details.get("present") if home_presence else None
    office_present = office_presence.details.get("present") if office_presence else None
    workstation_active = workstation.details.get("user_active") if workstation else None
    screen_awake = workstation.details.get("screen_awake") if workstation else None
    display_idle_seconds = (
        workstation.details.get("display_idle_seconds") if workstation else None
    )

    if home_presence and home_presence.fresh and home_present is False:
        state = "away"
    elif home_presence and home_presence.fresh and home_present is True:
        if office_presence and office_presence.fresh and office_present is False:
            state = "home_not_office"
        elif workstation and workstation.fresh and workstation.status == "active":
            state = "office_active"
        elif office_presence and office_presence.fresh and office_present is True:
            state = "office_idle"
        else:
            state = "home_idle"
    elif workstation and workstation.fresh and workstation.status == "active":
        state = "workstation_active"
    else:
        state = "unknown"

    summary_map = {
        "away": "Away from home.",
        "home_not_office": "Home, but not in the office zone.",
        "home_idle": "Home and quiet.",
        "office_idle": "In the office, but not active at the workstation.",
        "office_active": "In the office and active at the workstation.",
        "workstation_active": "Active at the workstation, home presence unknown.",
        "unknown": "Operator presence is not established yet.",
    }
    observed_candidates = [
        item.observed_at for item in sources if item.observed_at is not None
    ]
    observed_at = max(observed_candidates) if observed_candidates else None

    return OperatorStateOut(
        state=state,
        summary=summary_map[state],
        confidence=_confidence_for(sources),
        observed_at=observed_at,
        home_present=home_present,
        office_present=office_present,
        workstation_active=workstation_active,
        screen_awake=screen_awake,
        display_idle_seconds=display_idle_seconds,
        sources=sources,
    )
