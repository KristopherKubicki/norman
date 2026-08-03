"""Central, deterministic admission broker for observe-only Kaizen."""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.console_runtime import ConsoleRuntimeJobRecord
from app.services.console_runtime.types import ConsoleJobStatus
from app.services.kaizen.analysis import KaizenShadowAnalyzer, kaizen_shadow_analyzer
from app.services.kaizen.evidence import collect_runtime_observations
from app.services.kaizen.reports import write_daily_report
from app.services.kaizen.store import DbKaizenStore, db_kaizen_store
from app.services.kaizen.types import (
    BrokerDecision,
    KaizenConfig,
    as_utc,
    utc_now,
)


class KaizenBroker:
    """Evaluate a pilot TUI once without creating work or external effects."""

    def __init__(
        self,
        *,
        store: DbKaizenStore | None = None,
        shadow_analyzer: KaizenShadowAnalyzer | None = None,
    ) -> None:
        self._store = store or db_kaizen_store
        self._shadow_analyzer = shadow_analyzer or kaizen_shadow_analyzer

    def tick(
        self,
        db: Session,
        *,
        user_id: int,
        realm: str,
        source_tui: str,
        config: KaizenConfig,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Record one deterministic decision and a report after an idle no-op."""
        now = as_utc(now or utc_now())
        decision = self._evaluate(
            db,
            user_id=user_id,
            realm=realm,
            source_tui=source_tui,
            config=config,
            now=now,
        )
        audit = self._store.record_broker_decision(
            db, user_id=user_id, decision=decision
        )
        if decision.result != "observe_only":
            return {"decision": decision.as_dict(), "audit": audit, "report": None}
        observations = collect_runtime_observations(
            db, user_id=user_id, realm=realm, now=now
        )
        self._store.record_observations(db, user_id=user_id, observations=observations)
        report = write_daily_report(
            db,
            user_id=user_id,
            realm=realm,
            config=config,
            now=now,
            store=self._store,
        )
        result = {"decision": decision.as_dict(), "audit": audit, "report": report}
        if not config.candidate_shadow_failure():
            result["shadow"] = self._shadow_analyzer.analyze(
                db,
                user_id=user_id,
                realm=realm,
                source_tui=source_tui,
                config=config,
                now=now,
            )
        return result

    def _evaluate(
        self,
        db: Session,
        *,
        user_id: int,
        realm: str,
        source_tui: str,
        config: KaizenConfig,
        now: datetime,
    ) -> BrokerDecision:
        scope_failure = config.scope_failure(realm=realm, source_tui=source_tui)
        if scope_failure:
            result = (
                "disabled"
                if scope_failure.startswith(("kaizen", "observe"))
                else "rejected"
            )
            return _decision(realm, source_tui, result, scope_failure, now)
        snapshot = self._store.latest_snapshot(
            db, user_id=user_id, realm=realm, source_tui=source_tui
        )
        if snapshot is None:
            return _decision(realm, source_tui, "skipped", "stale_snapshot", now)
        observed_at = _snapshot_time(snapshot.get("observed_at"))
        if observed_at is None:
            return _decision(realm, source_tui, "skipped", "stale_snapshot", now)
        if observed_at > now:
            return _decision(
                realm, source_tui, "skipped", "future_snapshot", now, observed_at
            )
        if _age_seconds(now, observed_at) > config.snapshot_max_age_seconds:
            return _decision(
                realm, source_tui, "skipped", "stale_snapshot", now, observed_at
            )
        gate_reason = _snapshot_gate(snapshot, config=config, now=now)
        if gate_reason:
            return _decision(
                realm, source_tui, "skipped", gate_reason, now, observed_at
            )
        runtime_reason = _runtime_gate(db, user_id=user_id)
        if runtime_reason:
            return _decision(
                realm, source_tui, "skipped", runtime_reason, now, observed_at
            )
        return _decision(
            realm,
            source_tui,
            "observe_only",
            "no_action_observe_only",
            now,
            observed_at,
        )


def _decision(
    realm: str,
    source_tui: str,
    result: str,
    reason: str,
    now: datetime,
    observed_at: datetime | None = None,
) -> BrokerDecision:
    return BrokerDecision(
        realm=realm,
        source_tui=source_tui,
        result=result,
        reason=reason,
        decided_at=now,
        snapshot_observed_at=observed_at,
    )


def _snapshot_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _age_seconds(now: datetime, observed_at: datetime) -> float:
    return max(0.0, (now - observed_at).total_seconds())


def _snapshot_gate(
    snapshot: dict[str, Any], *, config: KaizenConfig, now: datetime
) -> str:
    state = str(snapshot.get("state") or "")
    activity = str(snapshot.get("activity_state") or "")
    health = str(snapshot.get("health_state") or "")
    metrics = (
        snapshot.get("metrics") if isinstance(snapshot.get("metrics"), dict) else {}
    )
    if state != "idle" or activity != "idle" or health != "ok":
        return "foreground_or_health_blocked"
    if bool(snapshot.get("waiting_visible")):
        return "human_gate_blocked"
    if float(metrics.get("queue_depth") or 0) > 0:
        return "queue_human_gate_blocked"
    entered_at = _snapshot_time(snapshot.get("state_entered_at"))
    if entered_at is None or _age_seconds(now, entered_at) < config.idle_grace_seconds:
        return "idle_grace_not_elapsed"
    return ""


def _runtime_gate(db: Session, *, user_id: int) -> str:
    statuses = [
        ConsoleJobStatus.RUNNING.value,
        ConsoleJobStatus.QUEUED.value,
        ConsoleJobStatus.WAITING_APPROVAL.value,
    ]
    records = (
        db.query(ConsoleRuntimeJobRecord.status)
        .filter(
            ConsoleRuntimeJobRecord.user_id == user_id,
            ConsoleRuntimeJobRecord.status.in_(statuses),
        )
        .all()
    )
    states = {str(record[0]) for record in records}
    if ConsoleJobStatus.RUNNING.value in states:
        return "runtime_foreground_blocked"
    if ConsoleJobStatus.WAITING_APPROVAL.value in states:
        return "runtime_human_gate_blocked"
    if ConsoleJobStatus.QUEUED.value in states:
        return "runtime_queue_blocked"
    return ""


kaizen_broker = KaizenBroker()
