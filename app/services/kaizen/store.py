"""Database persistence for the Kaizen control plane."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.kaizen import (
    KaizenCandidateFingerprintRecord,
    KaizenCandidateRecord,
    KaizenKpiObservationRecord,
    KaizenPolicyActionRecord,
    KaizenReportRecord,
)
from app.services.kaizen.types import (
    BrokerDecision,
    KaizenCandidateStatus,
    KaizenShadowCandidatePayload,
    KpiObservation,
    TUI_SNAPSHOT_KPI_ID,
    as_utc,
    utc_iso,
    utc_now,
)


class DbKaizenStore:
    """Persist sanitized Kaizen facts, shadow candidates, reports, and audits."""

    def record_observations(
        self,
        db: Session,
        *,
        user_id: int,
        observations: list[KpiObservation],
    ) -> list[dict[str, Any]]:
        """Insert idempotent KPI observations in the caller's user scope."""
        records = [
            self._existing_or_new_observation(db, user_id=user_id, item=item)
            for item in observations
        ]
        db.commit()
        for record in records:
            db.refresh(record)
        return [_observation_dict(record) for record in records]

    def list_observations(
        self,
        db: Session,
        *,
        user_id: int,
        realm: str,
        source_tui: str = "",
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 250,
    ) -> list[dict[str, Any]]:
        """List a bounded, realm-filtered KPI observation window."""
        query = db.query(KaizenKpiObservationRecord).filter_by(
            user_id=user_id, realm=realm
        )
        if source_tui:
            query = query.filter_by(source_tui=source_tui)
        if since is not None:
            query = query.filter(KaizenKpiObservationRecord.observed_at >= since)
        if until is not None:
            query = query.filter(KaizenKpiObservationRecord.observed_at <= until)
        records = query.order_by(KaizenKpiObservationRecord.id.desc()).limit(
            max(1, min(int(limit), 1000))
        )
        return [_observation_dict(record) for record in records]

    def latest_snapshot(
        self, db: Session, *, user_id: int, realm: str, source_tui: str
    ) -> dict[str, Any] | None:
        """Return the newest sanitized snapshot for one TUI, if present."""
        record = (
            db.query(KaizenKpiObservationRecord)
            .filter_by(
                user_id=user_id,
                realm=realm,
                source_tui=source_tui,
                kpi_id=TUI_SNAPSHOT_KPI_ID,
            )
            .order_by(KaizenKpiObservationRecord.observed_at.desc())
            .first()
        )
        if record is None:
            return None
        details = record.details_json if isinstance(record.details_json, dict) else {}
        return dict(details)

    def list_fresh_pilot_snapshot_scopes(
        self,
        db: Session,
        *,
        pilot_tui_ids: tuple[str, ...],
        allowed_realms: tuple[str, ...],
        observed_after: datetime,
        observed_before: datetime,
        after_scope: tuple[int, str, str] | None = None,
        limit: int = 1,
    ) -> list[tuple[int, str, str]]:
        """Return stable pilot scopes whose newest snapshot is in the fresh window."""
        bounded_limit = max(0, min(int(limit), 1000))
        if (
            bounded_limit == 0
            or not pilot_tui_ids
            or not allowed_realms
            or observed_after > observed_before
        ):
            return []

        record = KaizenKpiObservationRecord
        latest_per_scope = (
            db.query(
                record.user_id.label("user_id"),
                record.realm.label("realm"),
                record.source_tui.label("source_tui"),
                func.max(record.observed_at).label("observed_at"),
            )
            .filter(record.kpi_id == TUI_SNAPSHOT_KPI_ID)
            .group_by(record.user_id, record.realm, record.source_tui)
            .subquery()
        )
        query = (
            db.query(record.user_id, record.realm, record.source_tui)
            .join(
                latest_per_scope,
                and_(
                    record.user_id == latest_per_scope.c.user_id,
                    record.realm == latest_per_scope.c.realm,
                    record.source_tui == latest_per_scope.c.source_tui,
                    record.observed_at == latest_per_scope.c.observed_at,
                ),
            )
            .filter(record.kpi_id == TUI_SNAPSHOT_KPI_ID)
            .filter(record.realm.in_(allowed_realms))
            .filter(record.source_tui.in_(pilot_tui_ids))
            .filter(record.observed_at >= observed_after)
            .filter(record.observed_at <= observed_before)
            .distinct()
        )
        if after_scope is not None:
            after_user_id, after_realm, after_source_tui = after_scope
            query = query.filter(
                or_(
                    record.user_id > after_user_id,
                    and_(
                        record.user_id == after_user_id,
                        record.realm > after_realm,
                    ),
                    and_(
                        record.user_id == after_user_id,
                        record.realm == after_realm,
                        record.source_tui > after_source_tui,
                    ),
                )
            )
        rows = (
            query.order_by(record.user_id, record.realm, record.source_tui)
            .limit(bounded_limit)
            .all()
        )
        return [
            (int(user_id), str(realm), str(source_tui))
            for user_id, realm, source_tui in rows
        ]

    def record_broker_decision(
        self, db: Session, *, user_id: int, decision: BrokerDecision
    ) -> dict[str, Any]:
        """Persist a broker evaluation as a no-effect audit receipt."""
        payload = decision.as_dict()
        record = KaizenPolicyActionRecord(
            user_id=user_id,
            realm=decision.realm,
            source_tui=decision.source_tui,
            action_id=f"kad_{uuid4().hex}",
            policy_id="kaizen.broker_admission",
            state=decision.result,
            idempotency_key="",
            trigger_json={"reason": decision.reason},
            bounds_json={"phase": "observe_only", "effect": "none"},
            receipt_json=payload,
            verification_json={"state": "not_applicable"},
            rollback_json={},
            created_at=decision.decided_at,
            updated_at=decision.decided_at,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return _decision_dict(record)

    def save_report(
        self,
        db: Session,
        *,
        user_id: int,
        realm: str,
        kind: str,
        period_key: str,
        period_start: datetime,
        period_end: datetime,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Create or refresh one deterministic report for its reporting period."""
        record = _report_for_period(
            db,
            user_id=user_id,
            realm=realm,
            kind=kind,
            period_key=period_key,
        )
        if record is None:
            record = KaizenReportRecord(
                user_id=user_id,
                realm=realm,
                report_id=f"kr_{uuid4().hex}",
                kind=kind,
                period_key=period_key,
                period_start=period_start,
                period_end=period_end,
                delivery_state="api_only",
                payload_json=payload,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.add(record)
        else:
            record.period_start = period_start
            record.period_end = period_end
            record.payload_json = payload
            record.updated_at = utc_now()
            db.add(record)
        db.commit()
        db.refresh(record)
        return _report_dict(record)

    def latest_report(
        self, db: Session, *, user_id: int, realm: str, kind: str
    ) -> dict[str, Any] | None:
        """Load the newest report for the caller and realm."""
        record = (
            db.query(KaizenReportRecord)
            .filter_by(user_id=user_id, realm=realm, kind=kind)
            .order_by(KaizenReportRecord.period_end.desc())
            .first()
        )
        return _report_dict(record) if record is not None else None

    def shadow_token_usage(
        self,
        db: Session,
        *,
        user_id: int,
        realm: str,
        since: datetime,
    ) -> int:
        """Return conservatively charged local-model tokens for the UTC window."""
        records = (
            db.query(KaizenPolicyActionRecord.receipt_json)
            .filter_by(
                user_id=user_id,
                realm=realm,
                policy_id="kaizen.candidate_shadow",
            )
            .filter(KaizenPolicyActionRecord.created_at >= since)
            .all()
        )
        total = 0
        for (receipt,) in records:
            usage = receipt.get("usage") if isinstance(receipt, dict) else {}
            try:
                total += max(0, int((usage or {}).get("charged_tokens") or 0))
            except (TypeError, ValueError):
                continue
        return total

    def record_shadow_outcome(
        self,
        db: Session,
        *,
        user_id: int,
        realm: str,
        source_tui: str,
        state: str,
        reason: str,
        evidence_refs: list[str],
        receipt: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        """Audit a bounded shadow analysis result without retaining model text."""
        record = KaizenPolicyActionRecord(
            user_id=user_id,
            realm=realm,
            source_tui=source_tui,
            action_id=f"kas_{uuid4().hex}",
            policy_id="kaizen.candidate_shadow",
            state=state,
            idempotency_key="",
            trigger_json={
                "reason": reason,
                "evidence_refs": list(evidence_refs[:8]),
            },
            bounds_json={
                "phase": "candidate_shadow",
                "effect": "none",
                "target_mutation": False,
            },
            receipt_json=dict(receipt),
            verification_json={"state": "not_applicable"},
            rollback_json={},
            created_at=now,
            updated_at=now,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return _shadow_outcome_dict(record)

    def save_shadow_candidate(
        self,
        db: Session,
        *,
        user_id: int,
        realm: str,
        source_tui: str,
        payload: KaizenShadowCandidatePayload,
        fingerprint: str,
        model_receipt_ref: str,
        now: datetime,
    ) -> tuple[dict[str, Any] | None, str]:
        """Persist one validated shadow candidate unless its fingerprint is active."""
        fingerprint_record = (
            db.query(KaizenCandidateFingerprintRecord)
            .filter_by(
                user_id=user_id,
                realm=realm,
                target_type=payload.target_type.value,
                fingerprint=fingerprint,
            )
            .first()
        )
        if _fingerprint_suppressed(
            db, fingerprint_record=fingerprint_record, user_id=user_id, now=now
        ):
            assert fingerprint_record is not None
            fingerprint_record.last_seen_at = now
            fingerprint_record.updated_at = now
            db.add(fingerprint_record)
            db.commit()
            return None, "fingerprint_suppressed"

        expiry_at = as_utc(payload.proposal.expiry_at)
        proposal = payload.proposal.dict()
        proposal["expiry_at"] = utc_iso(expiry_at)
        candidate_id = f"kc_{uuid4().hex}"
        record = KaizenCandidateRecord(
            user_id=user_id,
            candidate_id=candidate_id,
            realm=realm,
            source_tui=source_tui,
            lane=payload.lane.value,
            target_type=payload.target_type.value,
            target_ref=payload.target_ref,
            fingerprint=fingerprint,
            status=KaizenCandidateStatus.SHADOW.value,
            severity=payload.severity.value,
            risk_tier=payload.risk_tier.value,
            impact_score=float(payload.impact_score),
            confidence_score=float(payload.confidence_score),
            evidence_refs_json=list(payload.evidence_refs),
            evidence_summary=payload.evidence_summary,
            proposal_json=proposal,
            model_receipt_ref=model_receipt_ref,
            expires_at=expiry_at,
            created_at=now,
            updated_at=now,
        )
        db.add(record)
        if fingerprint_record is None:
            fingerprint_record = KaizenCandidateFingerprintRecord(
                user_id=user_id,
                realm=realm,
                target_type=payload.target_type.value,
                fingerprint=fingerprint,
                active_candidate_id=candidate_id,
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        else:
            fingerprint_record.active_candidate_id = candidate_id
            fingerprint_record.last_seen_at = now
            fingerprint_record.updated_at = now
        db.add(fingerprint_record)
        db.commit()
        db.refresh(record)
        return _candidate_dict(record), "stored"

    def list_shadow_candidates(
        self,
        db: Session,
        *,
        user_id: int,
        realm: str,
        source_tui: str = "",
        lane: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return the API-only shadow view for one user and permitted realm."""
        query = db.query(KaizenCandidateRecord).filter_by(
            user_id=user_id,
            realm=realm,
            status=KaizenCandidateStatus.SHADOW.value,
        )
        if source_tui:
            query = query.filter_by(source_tui=source_tui)
        if lane:
            query = query.filter_by(lane=lane)
        records = query.order_by(KaizenCandidateRecord.created_at.desc()).limit(
            max(1, min(int(limit), 250))
        )
        return [_candidate_dict(record) for record in records]

    def _existing_or_new_observation(
        self, db: Session, *, user_id: int, item: KpiObservation
    ) -> KaizenKpiObservationRecord:
        record = (
            db.query(KaizenKpiObservationRecord)
            .filter_by(
                user_id=user_id,
                realm=item.realm,
                source_tui=item.source_tui,
                kpi_id=item.kpi_id,
                observed_at=item.observed_at,
            )
            .first()
        )
        if record is not None:
            return record
        record = _observation_record(user_id=user_id, item=item)
        db.add(record)
        return record


def _report_for_period(
    db: Session,
    *,
    user_id: int,
    realm: str,
    kind: str,
    period_key: str,
) -> KaizenReportRecord | None:
    return (
        db.query(KaizenReportRecord)
        .filter_by(
            user_id=user_id,
            realm=realm,
            kind=kind,
            period_key=period_key,
        )
        .first()
    )


def _fingerprint_suppressed(
    db: Session,
    *,
    fingerprint_record: KaizenCandidateFingerprintRecord | None,
    user_id: int,
    now: datetime,
) -> bool:
    if fingerprint_record is None:
        return False
    if (
        fingerprint_record.cooldown_until is not None
        and as_utc(fingerprint_record.cooldown_until) > now
    ):
        return True
    if (
        fingerprint_record.snoozed_until is not None
        and as_utc(fingerprint_record.snoozed_until) > now
    ):
        return True
    active_candidate_id = str(fingerprint_record.active_candidate_id or "")
    if not active_candidate_id:
        return False
    candidate = (
        db.query(KaizenCandidateRecord)
        .filter_by(user_id=user_id, candidate_id=active_candidate_id)
        .first()
    )
    if candidate is None:
        return False
    if candidate.expires_at is None:
        return True
    return as_utc(candidate.expires_at) > now


def _observation_record(
    *, user_id: int, item: KpiObservation
) -> KaizenKpiObservationRecord:
    return KaizenKpiObservationRecord(
        user_id=user_id,
        realm=item.realm,
        source_tui=item.source_tui,
        kpi_id=item.kpi_id,
        definition_version=item.definition_version,
        source_type=item.source_type,
        value_numeric=item.value_numeric,
        unit=item.unit,
        state=item.state,
        confidence=item.confidence,
        window_start=item.window_start,
        window_end=item.window_end,
        observed_at=item.observed_at,
        details_json=dict(item.details),
        evidence_refs_json=list(item.evidence_refs),
    )


def _observation_dict(record: KaizenKpiObservationRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "schema": "norman.kaizen-kpi-observation.v1",
        "kpi_id": record.kpi_id,
        "realm": record.realm,
        "source_tui": record.source_tui,
        "definition_version": record.definition_version,
        "source_type": record.source_type,
        "value_numeric": record.value_numeric,
        "unit": record.unit,
        "state": record.state,
        "confidence": record.confidence,
        "window_start": utc_iso(as_utc(record.window_start)),
        "window_end": utc_iso(as_utc(record.window_end)),
        "observed_at": utc_iso(as_utc(record.observed_at)),
        "details": dict(record.details_json or {}),
        "evidence_refs": list(record.evidence_refs_json or []),
    }


def _report_dict(record: KaizenReportRecord) -> dict[str, Any]:
    return {
        "report_id": record.report_id,
        "realm": record.realm,
        "kind": record.kind,
        "period_key": record.period_key,
        "period_start": utc_iso(as_utc(record.period_start)),
        "period_end": utc_iso(as_utc(record.period_end)),
        "delivery_state": record.delivery_state,
        "created_at": utc_iso(as_utc(record.created_at)),
        "updated_at": utc_iso(as_utc(record.updated_at)),
        "payload": dict(record.payload_json or {}),
    }


def _decision_dict(record: KaizenPolicyActionRecord) -> dict[str, Any]:
    return {
        "action_id": record.action_id,
        "policy_id": record.policy_id,
        "state": record.state,
        "realm": record.realm,
        "source_tui": record.source_tui,
        "receipt": dict(record.receipt_json or {}),
        "effect": "none",
    }


def _shadow_outcome_dict(record: KaizenPolicyActionRecord) -> dict[str, Any]:
    return {
        "action_id": record.action_id,
        "policy_id": record.policy_id,
        "state": record.state,
        "realm": record.realm,
        "source_tui": record.source_tui,
        "reason": str((record.trigger_json or {}).get("reason") or ""),
        "effect": "none",
    }


def _candidate_dict(record: KaizenCandidateRecord) -> dict[str, Any]:
    proposal = dict(record.proposal_json or {})
    expiry_at = (
        utc_iso(as_utc(record.expires_at)) if record.expires_at is not None else None
    )
    if expiry_at:
        proposal["expiry_at"] = expiry_at
    return {
        "schema": "norman.kaizen-candidate.v1",
        "candidate_id": record.candidate_id,
        "fingerprint": record.fingerprint,
        "realm": record.realm,
        "source_tui": record.source_tui,
        "lane": record.lane,
        "target_type": record.target_type,
        "target_ref": record.target_ref,
        "status": record.status,
        "visibility": "shadow_api_only",
        "severity": record.severity,
        "risk_tier": record.risk_tier,
        "impact_score": record.impact_score,
        "confidence_score": record.confidence_score,
        "evidence_refs": list(record.evidence_refs_json or []),
        "evidence_summary": record.evidence_summary,
        "proposal": proposal,
        "model_receipt_ref": record.model_receipt_ref,
        "expires_at": expiry_at,
        "created_at": utc_iso(as_utc(record.created_at)),
        "updated_at": utc_iso(as_utc(record.updated_at)),
    }


db_kaizen_store = DbKaizenStore()
