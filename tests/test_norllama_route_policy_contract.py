from __future__ import annotations

from datetime import datetime, timezone

from app.services.console_runtime.policy import with_local_first_catalog_defaults
from app.services.norllama.route_policy import (
    ROUTE_POLICY_VERSION,
    route_policy_contract,
    route_policy_hash,
    route_policy_lifecycle,
)


def test_route_policy_contract_is_versioned_compiled_authority():
    contract = route_policy_contract()

    assert contract["version"] == ROUTE_POLICY_VERSION
    assert len(contract["policy_hash"]) == 64
    assert (
        contract["policy_id"]
        == f"{ROUTE_POLICY_VERSION}:{contract['policy_hash'][:12]}"
    )
    assert route_policy_hash(contract) == contract["policy_hash"]
    assert contract["compiled_at"]
    assert contract["expires_at"]
    assert contract["models"]["router"]
    assert contract["lanes"]["planner"]["gate"] == "production"
    assert contract["placement"]["frontdoor"] == "https://llm.home.arpa"
    assert contract["residency"]["resident"]
    assert contract["fallbacks"]["worker_mismatch_requires_receipt_fallback"] is True
    assert contract["cloud_policy"]["cloud_proxy_counts_as_cloud"] is True
    assert contract["lifecycle_policy"]["expiry_enforced"] is True
    assert contract["lifecycle_policy"]["expired_state"] == "expired_blocked"
    assert contract["emergency_overlays"]["requires_expiration"] is True


def test_console_runtime_defaults_embed_same_route_policy_artifact():
    contract = route_policy_contract()
    policy = with_local_first_catalog_defaults({})

    assert policy["route_policy_version"] == contract["version"]
    assert policy["route_policy_id"] == contract["policy_id"]
    assert policy["route_policy_hash"] == contract["policy_hash"]
    assert policy["route_policy_artifact"] == contract
    assert policy["route_policy_lifecycle"]["policy_id"] == contract["policy_id"]
    assert policy["route_policy_lifecycle"]["default_route_allowed"] is True
    assert policy["placement_policy"] == contract["placement"]
    assert policy["residency_policy"] == contract["residency"]
    assert policy["fallback_policy"] == contract["fallbacks"]
    assert policy["cloud_policy"] == contract["cloud_policy"]


def test_route_policy_lifecycle_reports_valid_expiring_and_expired_states():
    contract = route_policy_contract()

    valid = route_policy_lifecycle(
        contract,
        now=datetime(2026, 7, 13, 0, 0, 0, tzinfo=timezone.utc),
    )
    assert valid["state"] == "valid"
    assert valid["default_route_allowed"] is True
    assert valid["degraded"] is False

    expiring = route_policy_lifecycle(
        contract,
        now=datetime(2026, 7, 16, 0, 0, 1, tzinfo=timezone.utc),
    )
    assert expiring["state"] == "expiring_soon"
    assert expiring["severity"] == "warning"
    assert expiring["default_route_allowed"] is True

    expired = route_policy_lifecycle(
        contract,
        now=datetime(2026, 7, 17, 0, 0, 1, tzinfo=timezone.utc),
    )
    assert expired["state"] == "expired_blocked"
    assert expired["severity"] == "critical"
    assert expired["default_route_allowed"] is False
    assert expired["manual_degraded_allowed"] is True
    assert expired["degraded"] is True


def test_route_policy_lifecycle_fails_closed_on_bad_timestamp():
    contract = route_policy_contract()
    contract["expires_at"] = "not-a-date"

    lifecycle = route_policy_lifecycle(
        contract,
        now=datetime(2026, 7, 13, 0, 0, 0, tzinfo=timezone.utc),
    )

    assert lifecycle["state"] == "refresh_failed"
    assert lifecycle["severity"] == "critical"
    assert lifecycle["default_route_allowed"] is False
    assert lifecycle["degraded"] is True
