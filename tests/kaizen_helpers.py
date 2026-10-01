"""Shared fixtures for observe-only Kaizen tests."""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import User
from app.services.kaizen.types import KpiObservation, TuiKpiSnapshot


def create_kaizen_user(db: Session) -> User:
    """Create an isolated database user for one Kaizen test."""
    token = uuid4().hex
    user = User(
        username=f"kaizen_{token}",
        email=f"kaizen_{token}@example.com",
        password="test-password",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def tui_snapshot(
    *,
    realm: str = "personal/home",
    source_tui: str = "pilot-1",
    observed_at: datetime | None = None,
    state_entered_at: datetime | None = None,
    state: str = "idle",
    activity_state: str = "idle",
    health_state: str = "ok",
    waiting_visible: bool = False,
    queue_depth: float = 0.0,
) -> TuiKpiSnapshot:
    """Build a complete, aggregate-only snapshot for a test."""
    observed_at = observed_at or datetime.now(timezone.utc)
    state_entered_at = state_entered_at or observed_at - timedelta(minutes=20)
    return TuiKpiSnapshot.model_validate(
        tui_snapshot_payload(
            realm=realm,
            source_tui=source_tui,
            observed_at=observed_at,
            state_entered_at=state_entered_at,
            state=state,
            activity_state=activity_state,
            health_state=health_state,
            waiting_visible=waiting_visible,
            queue_depth=queue_depth,
        )
    )


def tui_snapshot_payload(**overrides: Any) -> dict[str, Any]:
    """Return the JSON-compatible fixed snapshot contract."""
    observed_at = overrides.pop("observed_at", datetime.now(timezone.utc))
    state_entered_at = overrides.pop(
        "state_entered_at", observed_at - timedelta(minutes=20)
    )
    payload = {
        "schema": "norman.kaizen-tui-snapshot.v1",
        "realm": "personal/home",
        "source_tui": "pilot-1",
        "observed_at": observed_at.isoformat(),
        "state": "idle",
        "activity_state": "idle",
        "health_state": "ok",
        "prompt_visible": True,
        "waiting_visible": False,
        "state_entered_at": state_entered_at.isoformat(),
        "metrics": {
            "turns": 10,
            "successful_turns": 9,
            "failed_turns": 1,
            "avg_turn_seconds": 12,
            "last_turn_at": observed_at.timestamp(),
            "pending_seconds": 0,
            "queue_depth": 0,
            "wedge_count": 0,
            "blocked_count": 0,
            "degraded_count": 0,
            "state_changes": 2,
        },
    }
    metrics = payload["metrics"]
    metrics["queue_depth"] = overrides.pop("queue_depth", metrics["queue_depth"])
    payload.update(overrides)
    return payload


def kpi_observation(
    *,
    kpi_id: str,
    observed_at: datetime,
    realm: str = "personal/home",
    source_tui: str = "pilot-1",
    value: float | None = 1.0,
    state: str = "healthy",
    details: dict[str, Any] | None = None,
) -> KpiObservation:
    """Build a single deterministic observation for store and report tests."""
    return KpiObservation(
        kpi_id=kpi_id,
        realm=realm,
        source_tui=source_tui,
        definition_version="v1",
        source_type="test",
        value_numeric=value,
        unit="rate",
        state=state,
        confidence=1.0,
        window_start=observed_at,
        window_end=observed_at,
        observed_at=observed_at,
        details=details or {},
        evidence_refs=[],
    )
