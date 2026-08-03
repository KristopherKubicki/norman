"""Admission-gate tests for the no-effect Kaizen broker."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models import KaizenCandidateRecord
from app.models.console_runtime import ConsoleRuntimeJobRecord
from app.services.console_runtime.types import ConsoleJobStatus
from app.services.kaizen.analysis import KaizenShadowAnalyzer
from app.services.kaizen.broker import KaizenBroker
from app.services.kaizen.evidence import build_tui_observations
from app.services.kaizen.store import DbKaizenStore
from app.services.kaizen.types import KaizenConfig
from app.services.norllama.types import (
    NorllamaReceipt,
    NorllamaRoute,
    NorllamaTaskRequest,
)
from tests.kaizen_helpers import create_kaizen_user, tui_snapshot


def _config(**overrides) -> KaizenConfig:
    values = {
        "enabled": True,
        "observe_only": True,
        "pilot_tui_ids": ("pilot-1",),
        "allowed_realms": ("personal/home",),
        "idle_grace_seconds": 900,
        "snapshot_max_age_seconds": 300,
    }
    values.update(overrides)
    return KaizenConfig(**values)


def _record_snapshot(db, *, user_id: int, **kwargs) -> None:
    snapshot = tui_snapshot(**kwargs)
    DbKaizenStore().record_observations(
        db,
        user_id=user_id,
        observations=build_tui_observations(snapshot),
    )


@pytest.mark.parametrize(
    "config, realm, source_tui, result, reason",
    [
        (
            _config(enabled=False),
            "personal/home",
            "pilot-1",
            "disabled",
            "kaizen_disabled",
        ),
        (_config(), "work", "pilot-1", "rejected", "realm_rejected"),
        (_config(), "personal/home", "other-tui", "rejected", "pilot_rejected"),
    ],
)
def test_broker_fails_closed_for_disabled_or_out_of_scope_requests(
    db, config, realm, source_tui, result, reason
) -> None:
    user = create_kaizen_user(db)
    outcome = KaizenBroker().tick(
        db,
        user_id=user.id,
        realm=realm,
        source_tui=source_tui,
        config=config,
        now=datetime(2026, 8, 2, 16, tzinfo=timezone.utc),
    )

    assert outcome["decision"]["result"] == result
    assert outcome["decision"]["reason"] == reason
    assert outcome["report"] is None
    assert db.query(KaizenCandidateRecord).filter_by(user_id=user.id).count() == 0


@pytest.mark.parametrize(
    "snapshot_kwargs, expected_reason",
    [
        (
            {
                "observed_at": datetime(2026, 8, 2, 15, 50, tzinfo=timezone.utc),
                "state_entered_at": datetime(2026, 8, 2, 15, tzinfo=timezone.utc),
            },
            "stale_snapshot",
        ),
        (
            {
                "observed_at": datetime(2026, 8, 2, 16, 1, tzinfo=timezone.utc),
            },
            "future_snapshot",
        ),
        ({"state": "working"}, "foreground_or_health_blocked"),
        ({"waiting_visible": True}, "human_gate_blocked"),
        ({"queue_depth": 1}, "queue_human_gate_blocked"),
        (
            {"state_entered_at": datetime(2026, 8, 2, 15, 50, tzinfo=timezone.utc)},
            "idle_grace_not_elapsed",
        ),
    ],
)
def test_broker_skips_non_idle_or_stale_snapshots(
    db, snapshot_kwargs, expected_reason
) -> None:
    user = create_kaizen_user(db)
    now = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)
    values = {"observed_at": now}
    values.update(snapshot_kwargs)
    _record_snapshot(db, user_id=user.id, **values)

    outcome = KaizenBroker().tick(
        db,
        user_id=user.id,
        realm="personal/home",
        source_tui="pilot-1",
        config=_config(),
        now=now,
    )

    assert outcome["decision"]["result"] == "skipped"
    assert outcome["decision"]["reason"] == expected_reason
    assert outcome["report"] is None


@pytest.mark.parametrize(
    "status, expected_reason",
    [
        (ConsoleJobStatus.RUNNING, "runtime_foreground_blocked"),
        (ConsoleJobStatus.WAITING_APPROVAL, "runtime_human_gate_blocked"),
        (ConsoleJobStatus.QUEUED, "runtime_queue_blocked"),
    ],
)
def test_broker_defers_to_active_console_runtime_work(
    db, status, expected_reason
) -> None:
    user = create_kaizen_user(db)
    now = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)
    _record_snapshot(db, user_id=user.id, observed_at=now)
    db.add(
        ConsoleRuntimeJobRecord(
            user_id=user.id,
            job_id=f"kaizen-runtime-{uuid4().hex}",
            status=status.value,
            objective="Foreground work",
            contract_json={},
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()

    outcome = KaizenBroker().tick(
        db,
        user_id=user.id,
        realm="personal/home",
        source_tui="pilot-1",
        config=_config(),
        now=now,
    )

    assert outcome["decision"]["reason"] == expected_reason
    assert outcome["report"] is None


def test_broker_records_only_observations_and_report_after_idle_grace(db) -> None:
    user = create_kaizen_user(db)
    now = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)
    _record_snapshot(
        db,
        user_id=user.id,
        observed_at=now,
        state_entered_at=now - timedelta(minutes=16),
    )

    outcome = KaizenBroker().tick(
        db,
        user_id=user.id,
        realm="personal/home",
        source_tui="pilot-1",
        config=_config(),
        now=now,
    )

    assert outcome["decision"]["result"] == "observe_only"
    assert outcome["decision"]["effect"] == "none"
    assert outcome["report"]["payload"]["automatic_actions"] == []
    assert outcome["report"]["payload"]["candidates"] == []
    assert "shadow" not in outcome
    assert db.query(KaizenCandidateRecord).filter_by(user_id=user.id).count() == 0


def test_broker_runs_shadow_analysis_only_after_all_idle_gates_pass(db) -> None:
    user = create_kaizen_user(db)
    now = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)
    _record_snapshot(
        db,
        user_id=user.id,
        observed_at=now,
        state_entered_at=now - timedelta(minutes=16),
    )
    requests: list[NorllamaTaskRequest] = []

    def invoker(request: NorllamaTaskRequest) -> NorllamaReceipt:
        requests.append(request)
        evidence_ref = json.loads(request.input_text)["evidence"][0]["ref"]
        payload = {
            "schema": "norman.kaizen-candidate.v1",
            "lane": "runbook",
            "target_type": "runbook",
            "target_ref": "docs/dohio_host_bot_lifecycle_runbook.md",
            "severity": "warning",
            "risk_tier": "read_only",
            "impact_score": 0.5,
            "confidence_score": 0.8,
            "evidence_refs": [evidence_ref],
            "evidence_summary": "The persisted KPI remains warning.",
            "proposal": {
                "summary": "Add the warning trend to the daily operational report.",
                "allowed_action": "report",
                "verification_plan": [
                    "Confirm the daily report includes the warning state."
                ],
                "expiry_at": (now + timedelta(days=1)).isoformat(),
            },
        }
        return NorllamaReceipt(
            task_id=request.task_id,
            task_kind=request.kind,
            route=NorllamaRoute(
                lane="kaizen_candidate_shadow",
                provider="norllama",
                provider_kind="norllama",
                capability="planner",
                model="local-test-model",
                endpoint="http://127.0.0.1:11434",
            ),
            status="completed",
            output={"text": json.dumps(payload), "usage": {"total_tokens": 8}},
        )

    analyzer = KaizenShadowAnalyzer(
        store=DbKaizenStore(),
        invoker=invoker,
        route_resolver=lambda _request: NorllamaRoute(
            lane="kaizen_candidate_shadow",
            provider="norllama",
            provider_kind="norllama",
            capability="planner",
            model="local-test-model",
            endpoint="http://127.0.0.1:11434",
        ),
    )
    outcome = KaizenBroker(shadow_analyzer=analyzer).tick(
        db,
        user_id=user.id,
        realm="personal/home",
        source_tui="pilot-1",
        config=_config(
            candidate_shadow_enabled=True,
            daily_norllama_token_budget=100,
            candidate_shadow_max_tokens=25,
            candidate_shadow_max_concurrency=1,
        ),
        now=now,
    )

    assert outcome["decision"]["result"] == "observe_only"
    assert outcome["shadow"]["state"] == "stored"
    assert len(requests) == 1
    assert db.query(KaizenCandidateRecord).filter_by(user_id=user.id).count() == 1


def test_broker_does_not_run_shadow_analysis_while_human_gate_is_visible(db) -> None:
    user = create_kaizen_user(db)
    now = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)
    _record_snapshot(db, user_id=user.id, observed_at=now, waiting_visible=True)
    calls = 0

    def invoker(_request: NorllamaTaskRequest) -> NorllamaReceipt:
        nonlocal calls
        calls += 1
        raise AssertionError("human-gated tick must not invoke Norllama")

    analyzer = KaizenShadowAnalyzer(store=DbKaizenStore(), invoker=invoker)
    outcome = KaizenBroker(shadow_analyzer=analyzer).tick(
        db,
        user_id=user.id,
        realm="personal/home",
        source_tui="pilot-1",
        config=_config(
            candidate_shadow_enabled=True,
            daily_norllama_token_budget=100,
            candidate_shadow_max_tokens=25,
            candidate_shadow_max_concurrency=1,
        ),
        now=now,
    )

    assert outcome["decision"]["reason"] == "human_gate_blocked"
    assert "shadow" not in outcome
    assert calls == 0
