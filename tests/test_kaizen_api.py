"""Authenticated API tests for the observe-only Kaizen foundation."""

from datetime import datetime, timedelta, timezone

import pytest

from app.api.deps import get_console_runtime_user
from app.core.config import settings
from app.main import app
from app.services.kaizen.store import DbKaizenStore
from app.services.kaizen.types import KaizenShadowCandidatePayload
from tests.kaizen_helpers import create_kaizen_user, tui_snapshot_payload


@pytest.fixture
def kaizen_api_client(test_app, db, monkeypatch):
    """Use an isolated user so other API tests cannot affect admission gates."""
    user = create_kaizen_user(db)

    async def current_user():
        return user

    monkeypatch.setitem(
        app.dependency_overrides, get_console_runtime_user, current_user
    )
    test_app.kaizen_test_user = user
    return test_app


def _enable_kaizen(monkeypatch) -> None:
    monkeypatch.setattr(settings, "kaizen_enabled", True)
    monkeypatch.setattr(settings, "kaizen_observe_only", True)
    monkeypatch.setattr(settings, "kaizen_auto_actions_enabled", False)
    monkeypatch.setattr(settings, "kaizen_pilot_tui_ids", ["api-pilot"])
    monkeypatch.setattr(settings, "kaizen_allowed_realms", ["personal/home"])


def _shadow_candidate(now: datetime) -> KaizenShadowCandidatePayload:
    return KaizenShadowCandidatePayload.model_validate(
        {
            "schema": "norman.kaizen-candidate.v1",
            "lane": "runbook",
            "target_type": "runbook",
            "target_ref": "docs/dohio_host_bot_lifecycle_runbook.md",
            "severity": "warning",
            "risk_tier": "read_only",
            "impact_score": 0.5,
            "confidence_score": 0.8,
            "evidence_refs": ["observation:1"],
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
    )


def test_kaizen_api_ingests_reports_and_reads_aggregate_kpis(
    kaizen_api_client, monkeypatch
) -> None:
    _enable_kaizen(monkeypatch)
    now = datetime.now(timezone.utc)
    snapshot = tui_snapshot_payload(
        source_tui="api-pilot",
        observed_at=now,
        state_entered_at=now - timedelta(minutes=20),
    )

    ingested = kaizen_api_client.post("/api/v1/kaizen/tui-snapshots", json=snapshot)
    ticked = kaizen_api_client.post(
        "/api/v1/kaizen/tick",
        json={"realm": "personal/home", "source_tui": "api-pilot"},
    )
    kpis = kaizen_api_client.get("/api/v1/kaizen/kpis?source_tui=api-pilot")
    report = kaizen_api_client.get("/api/v1/kaizen/reports/latest?kind=daily")

    assert ingested.status_code == 200
    assert ingested.json()["observation_count"] == 8
    assert ticked.status_code == 200
    assert ticked.json()["decision"]["result"] == "observe_only"
    assert ticked.json()["decision"]["effect"] == "none"
    assert kpis.status_code == 200
    assert {item["kpi_id"] for item in kpis.json()["items"]} >= {
        "tui_snapshot_state",
        "tui_queue_depth",
    }
    assert report.status_code == 200
    assert report.json()["payload"]["candidates"] == []
    assert report.json()["payload"]["automatic_actions"] == []


def test_kaizen_api_rejects_disabled_and_out_of_scope_ingestion(
    kaizen_api_client, monkeypatch
) -> None:
    snapshot = tui_snapshot_payload(source_tui="api-pilot")

    disabled = kaizen_api_client.post("/api/v1/kaizen/tui-snapshots", json=snapshot)
    _enable_kaizen(monkeypatch)
    rejected = kaizen_api_client.post(
        "/api/v1/kaizen/tui-snapshots",
        json={**snapshot, "realm": "work"},
    )

    assert disabled.status_code == 409
    assert rejected.status_code == 403


def test_kaizen_api_lists_only_realm_scoped_shadow_candidates(
    kaizen_api_client, db, monkeypatch
) -> None:
    _enable_kaizen(monkeypatch)
    now = datetime.now(timezone.utc)
    owner = kaizen_api_client.kaizen_test_user
    other = create_kaizen_user(db)
    store = DbKaizenStore()
    payload = _shadow_candidate(now)
    store.save_shadow_candidate(
        db,
        user_id=owner.id,
        realm="personal/home",
        source_tui="api-pilot",
        payload=payload,
        fingerprint="owner-fingerprint",
        model_receipt_ref="kas_owner",
        now=now,
    )
    store.save_shadow_candidate(
        db,
        user_id=other.id,
        realm="personal/home",
        source_tui="api-pilot",
        payload=payload,
        fingerprint="other-fingerprint",
        model_receipt_ref="kas_other",
        now=now,
    )

    listed = kaizen_api_client.get(
        "/api/v1/kaizen/candidates?source_tui=api-pilot&lane=runbook"
    )
    bad_lane = kaizen_api_client.get("/api/v1/kaizen/candidates?lane=unsupported")
    wrong_realm = kaizen_api_client.get("/api/v1/kaizen/candidates?realm=work")

    assert listed.status_code == 200
    assert listed.json()["status"] == "shadow"
    assert listed.json()["visibility"] == "shadow_api_only"
    assert len(listed.json()["items"]) == 1
    assert listed.json()["items"][0]["status"] == "shadow"
    assert bad_lane.status_code == 422
    assert wrong_realm.status_code == 403


def test_kaizen_status_exposes_shadow_mode_without_prepare_or_apply(
    kaizen_api_client, monkeypatch
) -> None:
    _enable_kaizen(monkeypatch)
    monkeypatch.setattr(settings, "kaizen_candidate_shadow_enabled", True)
    monkeypatch.setattr(settings, "kaizen_daily_norllama_token_budget", 100)
    monkeypatch.setattr(settings, "kaizen_candidate_shadow_max_tokens", 25)
    monkeypatch.setattr(settings, "kaizen_candidate_shadow_max_concurrency", 1)

    response = kaizen_api_client.get("/api/v1/kaizen/status")

    assert response.status_code == 200
    assert response.json()["phase"] == "candidate_shadow"
    assert response.json()["candidate_shadow"]["local_only"] is True
    assert {"notifications", "prepare", "apply"} <= set(response.json()["prohibited"])
