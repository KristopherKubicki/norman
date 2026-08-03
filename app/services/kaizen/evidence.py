"""Deterministic, sanitized evidence collectors for observe-only Kaizen."""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.console_runtime import ConsoleRuntimeJobRecord
from app.services.console_runtime.store import db_console_runtime_store
from app.services.console_runtime.types import ConsoleJobStatus
from app.services.kaizen.types import (
    KpiObservation,
    TUI_SNAPSHOT_KPI_ID,
    TuiKpiSnapshot,
    as_utc,
    utc_now,
)


def build_tui_observations(snapshot: TuiKpiSnapshot) -> list[KpiObservation]:
    """Build fixed KPI records from one already-sanitized TUI snapshot."""
    snapshot_evidence = snapshot.sanitized_payload()
    return [
        _snapshot_state_observation(snapshot, snapshot_evidence),
        _rate_observation(snapshot, "tui_foreground_blocked_rate", "blocked_count"),
        _rate_observation(snapshot, "tui_wedge_rate", "wedge_count"),
        _rate_observation(snapshot, "tui_failed_turn_rate", "failed_turns"),
        _metric_observation(snapshot, "tui_queue_depth", "queue_depth", "count"),
        _metric_observation(
            snapshot, "tui_pending_seconds", "pending_seconds", "seconds"
        ),
        _metric_observation(
            snapshot, "tui_avg_turn_seconds", "avg_turn_seconds", "seconds"
        ),
        _source_freshness_observation(snapshot),
    ]


def _snapshot_state_observation(
    snapshot: TuiKpiSnapshot, evidence: dict[str, Any]
) -> KpiObservation:
    return KpiObservation(
        kpi_id=TUI_SNAPSHOT_KPI_ID,
        realm=snapshot.realm,
        source_tui=snapshot.source_tui,
        definition_version="v1",
        source_type="tui_kpi_snapshot",
        value_numeric=_health_value(snapshot.health_state.value),
        unit="state",
        state=_snapshot_kpi_state(snapshot),
        confidence=1.0,
        window_start=snapshot.observed_at,
        window_end=snapshot.observed_at,
        observed_at=snapshot.observed_at,
        details=evidence,
        evidence_refs=[],
    )


def _rate_observation(
    snapshot: TuiKpiSnapshot, kpi_id: str, numerator_key: str
) -> KpiObservation:
    numerator = float(getattr(snapshot.metrics, numerator_key))
    denominator = max(float(snapshot.metrics.turns), 1.0)
    value = numerator / denominator
    state = "warning" if numerator else "healthy"
    if snapshot.state.value in ("blocked", "wedged"):
        state = "critical"
    return _snapshot_observation(
        snapshot, kpi_id, value, "rate", state, {"numerator": numerator}
    )


def _metric_observation(
    snapshot: TuiKpiSnapshot, kpi_id: str, metric_key: str, unit: str
) -> KpiObservation:
    value = float(getattr(snapshot.metrics, metric_key))
    state = "warning" if value else "healthy"
    return _snapshot_observation(snapshot, kpi_id, value, unit, state, {})


def _source_freshness_observation(snapshot: TuiKpiSnapshot) -> KpiObservation:
    return _snapshot_observation(
        snapshot,
        "report_source_freshness_rate",
        1.0,
        "rate",
        "healthy",
        {"source": "tui_kpi_snapshot"},
    )


def _snapshot_observation(
    snapshot: TuiKpiSnapshot,
    kpi_id: str,
    value: float,
    unit: str,
    state: str,
    details: dict[str, Any],
) -> KpiObservation:
    return KpiObservation(
        kpi_id=kpi_id,
        realm=snapshot.realm,
        source_tui=snapshot.source_tui,
        definition_version="v1",
        source_type="tui_kpi_snapshot",
        value_numeric=value,
        unit=unit,
        state=state,
        confidence=1.0,
        window_start=snapshot.observed_at,
        window_end=snapshot.observed_at,
        observed_at=snapshot.observed_at,
        details=details,
        evidence_refs=[],
    )


def collect_runtime_observations(
    db: Session, *, user_id: int, realm: str, now: datetime | None = None
) -> list[KpiObservation]:
    """Collect bounded aggregate runtime facts without any external requests."""
    now = as_utc(now or utc_now())
    return [
        _route_success_observation(db, user_id=user_id, realm=realm, now=now),
        _verification_pass_observation(db, user_id=user_id, realm=realm, now=now),
        _approval_wait_observation(db, user_id=user_id, realm=realm, now=now),
    ]


def _route_success_observation(
    db: Session, *, user_id: int, realm: str, now: datetime
) -> KpiObservation:
    summary = db_console_runtime_store.route_outcome_summary(db, user_id=user_id)
    count = int(summary.get("count") or 0)
    ok = int(summary.get("ok") or 0)
    value = float(ok / count) if count else None
    state = "healthy" if count and ok == count else "warning" if count else "missing"
    return _runtime_observation(
        "local_route_success_rate",
        realm,
        value,
        "rate",
        state,
        1.0 if count else 0.0,
        now,
        {"count": count, "ok": ok, "fail": int(summary.get("fail") or 0)},
    )


def _verification_pass_observation(
    db: Session, *, user_id: int, realm: str, now: datetime
) -> KpiObservation:
    records = db.query(ConsoleRuntimeJobRecord).filter_by(user_id=user_id).all()
    receipts = [
        receipt
        for record in records
        for receipt in (record.verification_receipts_json or [])
        if isinstance(receipt, dict)
    ]
    passing = sum(str(item.get("status") or "").lower() == "pass" for item in receipts)
    total = len(receipts)
    value = float(passing / total) if total else None
    state = (
        "healthy" if total and passing == total else "warning" if total else "missing"
    )
    return _runtime_observation(
        "runtime_job_verification_pass_rate",
        realm,
        value,
        "rate",
        state,
        1.0 if total else 0.0,
        now,
        {"receipts": total, "passing": passing},
    )


def _approval_wait_observation(
    db: Session, *, user_id: int, realm: str, now: datetime
) -> KpiObservation:
    waiting = (
        db.query(ConsoleRuntimeJobRecord)
        .filter_by(user_id=user_id, status=ConsoleJobStatus.WAITING_APPROVAL.value)
        .all()
    )
    ages = [
        max(0.0, (now - as_utc(record.created_at)).total_seconds())
        for record in waiting
    ]
    return _runtime_observation(
        "runtime_approval_wait_age",
        realm,
        max(ages, default=0.0),
        "seconds",
        "warning" if ages else "healthy",
        1.0,
        now,
        {"waiting_jobs": len(ages)},
    )


def _runtime_observation(
    kpi_id: str,
    realm: str,
    value: float | None,
    unit: str,
    state: str,
    confidence: float,
    now: datetime,
    details: dict[str, Any],
) -> KpiObservation:
    return KpiObservation(
        kpi_id=kpi_id,
        realm=realm,
        source_tui="",
        definition_version="v1",
        source_type="console_runtime",
        value_numeric=value,
        unit=unit,
        state=state,
        confidence=confidence,
        window_start=now,
        window_end=now,
        observed_at=now,
        details=details,
        evidence_refs=[],
    )


def _health_value(health_state: str) -> float:
    return {"ok": 1.0, "unknown": 0.5, "degraded": 0.25}.get(health_state, 0.0)


def _snapshot_kpi_state(snapshot: TuiKpiSnapshot) -> str:
    if snapshot.health_state.value in ("blocked", "wedged"):
        return "critical"
    if snapshot.health_state.value in ("degraded", "unknown"):
        return "warning"
    return "healthy"
