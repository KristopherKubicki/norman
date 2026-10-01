"""Tests for the local-only, proposal-only Kaizen shadow candidate boundary."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.models import KaizenCandidateRecord, KaizenPolicyActionRecord
from app.services.kaizen.analysis import KaizenShadowAnalyzer
from app.services.kaizen.store import DbKaizenStore
from app.services.kaizen.types import KaizenConfig
from app.services.norllama.types import (
    NorllamaReceipt,
    NorllamaRoute,
    NorllamaTaskRequest,
)
from tests.kaizen_helpers import create_kaizen_user, kpi_observation


def _config(**overrides) -> KaizenConfig:
    values = {
        "enabled": True,
        "observe_only": True,
        "candidate_shadow_enabled": True,
        "pilot_tui_ids": ("pilot-1",),
        "allowed_realms": ("personal/home",),
        "candidate_evidence_max_age_seconds": 300,
        "daily_norllama_token_budget": 100,
        "candidate_shadow_max_tokens": 25,
        "candidate_shadow_max_concurrency": 1,
    }
    values.update(overrides)
    return KaizenConfig(**values)


def _local_route() -> NorllamaRoute:
    return NorllamaRoute(
        lane="kaizen_candidate_shadow",
        provider="norllama",
        provider_kind="norllama",
        capability="planner",
        model="local-test-model",
        endpoint="http://127.0.0.1:11434",
        local=True,
        cloud_proxy=False,
    )


def _cloud_route() -> NorllamaRoute:
    return NorllamaRoute(
        lane="kaizen_candidate_shadow",
        provider="bedrock",
        provider_kind="bedrock",
        capability="planner",
        model="cloud-test-model",
        endpoint="https://example.invalid",
        mode="backup_online",
        local=False,
        cloud_proxy=True,
    )


def _receipt(
    request: NorllamaTaskRequest,
    text: str,
    *,
    route: NorllamaRoute | None = None,
    status: str = "completed",
    total_tokens: int = 0,
) -> NorllamaReceipt:
    return NorllamaReceipt(
        task_id=request.task_id,
        task_kind=request.kind,
        route=route or _local_route(),
        status=status,
        output={"text": text, "usage": {"total_tokens": total_tokens}},
    )


def _candidate_payload(
    evidence_ref: str, now: datetime, **overrides
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "norman.kaizen-candidate.v1",
        "lane": "runbook",
        "target_type": "runbook",
        "target_ref": "docs/dohio_host_bot_lifecycle_runbook.md",
        "severity": "warning",
        "risk_tier": "read_only",
        "impact_score": 0.5,
        "confidence_score": 0.8,
        "evidence_refs": [evidence_ref],
        "evidence_summary": "The persisted KPI is warning and needs reporting.",
        "proposal": {
            "summary": "Add the warning trend to the daily operational report.",
            "allowed_action": "report",
            "verification_plan": [
                "Confirm the daily report includes the warning state."
            ],
            "expiry_at": (now + timedelta(days=1)).isoformat(),
        },
    }
    for key, value in overrides.items():
        if key == "proposal" and isinstance(value, dict):
            proposal = dict(payload["proposal"])
            proposal.update(value)
            payload["proposal"] = proposal
        else:
            payload[key] = value
    return payload


def _record_warning(
    db,
    store: DbKaizenStore,
    *,
    user_id: int,
    now: datetime,
    source_tui: str = "pilot-1",
) -> str:
    result = store.record_observations(
        db,
        user_id=user_id,
        observations=[
            kpi_observation(
                kpi_id="tui_failed_turn_rate",
                observed_at=now,
                source_tui=source_tui,
                state="warning",
            )
        ],
    )
    return f"observation:{result[0]['id']}"


def _analyze(
    db,
    *,
    user_id: int,
    config: KaizenConfig,
    now: datetime,
    invoker,
    route_resolver=None,
) -> dict[str, object]:
    return KaizenShadowAnalyzer(
        store=DbKaizenStore(),
        invoker=invoker,
        route_resolver=route_resolver or (lambda _request: _local_route()),
    ).analyze(
        db,
        user_id=user_id,
        realm="personal/home",
        source_tui="pilot-1",
        config=config,
        now=now,
    )


def test_shadow_analysis_skips_without_warning_evidence_or_token_budget(db) -> None:
    store = DbKaizenStore()
    user = create_kaizen_user(db)
    now = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)
    calls: list[NorllamaTaskRequest] = []

    def invoker(request: NorllamaTaskRequest) -> NorllamaReceipt:
        calls.append(request)
        return _receipt(request, "{}")

    no_evidence = _analyze(
        db,
        user_id=user.id,
        config=_config(),
        now=now,
        invoker=invoker,
    )
    _record_warning(db, store, user_id=user.id, now=now)
    no_budget = _analyze(
        db,
        user_id=user.id,
        config=_config(daily_norllama_token_budget=0),
        now=now,
        invoker=invoker,
    )

    assert no_evidence["reason"] == "no_fresh_warning_evidence"
    assert no_budget["reason"] == "candidate_shadow_budget_disabled"
    assert calls == []


@pytest.mark.parametrize(
    "config", [_config(enabled=False), _config(observe_only=False)]
)
def test_shadow_analysis_requires_the_enabled_observe_only_scope(db, config) -> None:
    store = DbKaizenStore()
    user = create_kaizen_user(db)
    now = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)
    _record_warning(db, store, user_id=user.id, now=now)
    calls = 0

    def invoker(_request: NorllamaTaskRequest) -> NorllamaReceipt:
        nonlocal calls
        calls += 1
        raise AssertionError("out-of-scope shadow analysis must not invoke Norllama")

    outcome = _analyze(
        db,
        user_id=user.id,
        config=config,
        now=now,
        invoker=invoker,
    )

    assert outcome["reason"] in {"kaizen_disabled", "observe_only_required"}
    assert calls == 0


def test_shadow_analysis_rejects_planned_cloud_route_before_invocation(db) -> None:
    store = DbKaizenStore()
    user = create_kaizen_user(db)
    now = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)
    _record_warning(db, store, user_id=user.id, now=now)
    invoked = False

    def invoker(_request: NorllamaTaskRequest) -> NorllamaReceipt:
        nonlocal invoked
        invoked = True
        raise AssertionError("cloud plan must not reach the invoker")

    outcome = _analyze(
        db,
        user_id=user.id,
        config=_config(),
        now=now,
        invoker=invoker,
        route_resolver=lambda _request: _cloud_route(),
    )

    assert outcome["reason"] == "planned_route_not_local_norllama"
    assert invoked is False


def test_shadow_analysis_rejects_returned_cloud_receipt_and_charges_budget(db) -> None:
    store = DbKaizenStore()
    user = create_kaizen_user(db)
    now = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)
    _record_warning(db, store, user_id=user.id, now=now)

    def invoker(request: NorllamaTaskRequest) -> NorllamaReceipt:
        return _receipt(request, "{}", route=_cloud_route())

    outcome = _analyze(
        db,
        user_id=user.id,
        config=_config(),
        now=now,
        invoker=invoker,
    )
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    assert outcome["reason"] == "returned_route_not_local_norllama"
    assert (
        store.shadow_token_usage(
            db, user_id=user.id, realm="personal/home", since=midnight
        )
        == 25
    )


@pytest.mark.parametrize(
    "payload_override, expected_reason",
    [
        ({"raw": "not json"}, "model_output_invalid_json"),
        (
            {"raw": json.dumps({"schema": "norman.kaizen-candidate.v1"})},
            "model_output_schema_invalid",
        ),
        (
            {"evidence_summary": "Open https://example.invalid for the result."},
            "candidate_unsafe_text",
        ),
        (
            {"proposal": {"summary": "Set API_KEY=leaked in the report."}},
            "candidate_unsafe_text",
        ),
        (
            {"proposal": {"verification_plan": ["Run make test before reporting."]}},
            "candidate_unsafe_text",
        ),
        ({"target_ref": "docs/not-allowed.md"}, "candidate_target_not_allowed"),
        (
            {"proposal": {"allowed_action": "adjust_control_plane"}},
            "candidate_action_not_allowed",
        ),
        ({"evidence_refs": ["observation:999999"]}, "candidate_evidence_not_in_packet"),
    ],
)
def test_shadow_analysis_rejects_malformed_or_unsafe_candidates(
    db, payload_override, expected_reason
) -> None:
    store = DbKaizenStore()
    user = create_kaizen_user(db)
    now = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)
    evidence_ref = _record_warning(db, store, user_id=user.id, now=now)

    def invoker(request: NorllamaTaskRequest) -> NorllamaReceipt:
        raw = payload_override.get("raw")
        if not isinstance(raw, str):
            raw = json.dumps(_candidate_payload(evidence_ref, now, **payload_override))
        return _receipt(request, raw)

    outcome = _analyze(
        db,
        user_id=user.id,
        config=_config(),
        now=now,
        invoker=invoker,
    )

    assert outcome["reason"] == expected_reason
    assert db.query(KaizenCandidateRecord).filter_by(user_id=user.id).count() == 0


def test_shadow_analysis_rejects_stale_evidence_before_invocation(db) -> None:
    store = DbKaizenStore()
    user = create_kaizen_user(db)
    now = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)
    _record_warning(
        db,
        store,
        user_id=user.id,
        now=now - timedelta(minutes=6),
    )
    calls = 0

    def invoker(request: NorllamaTaskRequest) -> NorllamaReceipt:
        nonlocal calls
        calls += 1
        return _receipt(request, "{}")

    outcome = _analyze(
        db,
        user_id=user.id,
        config=_config(candidate_evidence_max_age_seconds=300),
        now=now,
        invoker=invoker,
    )

    assert outcome["reason"] == "no_fresh_warning_evidence"
    assert calls == 0


def test_shadow_analysis_stores_sanitized_candidate_and_suppresses_duplicate(
    db,
) -> None:
    store = DbKaizenStore()
    user = create_kaizen_user(db)
    now = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)
    evidence_ref = _record_warning(db, store, user_id=user.id, now=now)
    requests: list[NorllamaTaskRequest] = []

    def invoker(request: NorllamaTaskRequest) -> NorllamaReceipt:
        requests.append(request)
        return _receipt(
            request,
            json.dumps(_candidate_payload(evidence_ref, now)),
            total_tokens=8,
        )

    first = _analyze(
        db,
        user_id=user.id,
        config=_config(),
        now=now,
        invoker=invoker,
    )
    second = _analyze(
        db,
        user_id=user.id,
        config=_config(),
        now=now,
        invoker=invoker,
    )
    record = db.query(KaizenCandidateRecord).filter_by(user_id=user.id).one()
    audit = (
        db.query(KaizenPolicyActionRecord)
        .filter_by(action_id=record.model_receipt_ref)
        .one()
    )

    assert first["state"] == "stored"
    assert second["state"] == "suppressed"
    assert second["reason"] == "fingerprint_suppressed"
    assert record.status == "shadow"
    assert record.model_receipt_ref == first["audit"]["action_id"]
    assert audit.receipt_json["route"]["provider"] == "norllama"
    assert "endpoint" not in audit.receipt_json["route"]
    assert "text" not in audit.receipt_json
    assert len(requests) == 2
    assert requests[0].route_policy == {
        "provider": "norllama",
        "allow_cloud_proxy": False,
        "local_first": True,
        "max_tokens": 25,
        "endpoint": "http://127.0.0.1:11434",
    }
