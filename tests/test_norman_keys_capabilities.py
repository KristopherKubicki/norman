from __future__ import annotations

from app.api.deps import get_keys_service_user
from app.crud.user import create_user, get_user_by_email
from app.main import app
from app.schemas.user import UserCreate


FINGERPRINT = "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _keys_service_override(db):
    async def override():
        user = get_user_by_email(db, email="keys-capability@example.com")
        if not user:
            user = create_user(
                db,
                UserCreate(
                    email="keys-capability@example.com",
                    username="keys_capability_user",
                    password="pass123",
                ),
            )
        return user

    return override


def _setup_capability(test_app, *, name: str, host_id: str = "hal") -> None:
    enrollment = test_app.post(
        "/api/v1/keys/enrollments",
        json={
            "host_id": host_id,
            "hostname": f"{host_id}.home.arpa",
            "identity_fingerprint": FINGERPRINT,
            "requester_ids": ["hal-tui"],
            "capability_names": [name],
            "lanes": ["personal"],
            "notes": "test enrollment",
        },
    )
    assert enrollment.status_code == 201, enrollment.text
    capability = test_app.post(
        "/api/v1/keys/capabilities",
        json={
            "name": name,
            "executor_kind": "receipt",
            "executor_ref": "",
            "secret_aliases": ["networking/firewall"],
            "enabled": True,
        },
    )
    assert capability.status_code == 201, capability.text
    policy = test_app.post(
        "/api/v1/keys/capability-policies",
        json={
            "name": f"{name}-policy",
            "capability_name": name,
            "requester_type": "agent",
            "requester_id": "hal-tui",
            "lane": "personal",
            "allowed_actions": ["inspect"],
            "allowed_target_hosts": ["firewall.home.arpa"],
            "max_ttl_seconds": 300,
            "approval_required": False,
            "enabled": True,
        },
    )
    assert policy.status_code == 201, policy.text


def test_capability_route_requires_enrolled_host_and_returns_opaque_lease(
    test_app, db
) -> None:
    app.dependency_overrides[get_keys_service_user] = _keys_service_override(db)
    try:
        denied = test_app.post(
            "/v1/capabilities/request",
            headers={"X-Norman-Keys-Host-Fingerprint": FINGERPRINT},
            json={
                "capability": "networking.firewall.inspect",
                "host_id": "unknown-host",
                "identity_fingerprint": FINGERPRINT,
                "requester_type": "agent",
                "requester_id": "hal-tui",
                "lane": "personal",
                "action": "inspect",
                "parameters": {"target": "firewall.home.arpa"},
                "target_host": "firewall.home.arpa",
            },
        )
        assert denied.status_code == 403
        assert denied.json()["detail"] == "Host is not enrolled for Norman Keys"

        _setup_capability(test_app, name="networking.firewall.inspect")
        response = test_app.post(
            "/v1/capabilities/request",
            headers={"X-Norman-Keys-Host-Fingerprint": FINGERPRINT},
            json={
                "capability": "networking.firewall.inspect",
                "host_id": "hal",
                "identity_fingerprint": FINGERPRINT,
                "requester_type": "agent",
                "requester_id": "hal-tui",
                "session_id": "session-1",
                "lane": "personal",
                "action": "inspect",
                "parameters": {"target": "firewall.home.arpa"},
                "target_host": "firewall.home.arpa",
                "reason": "read-only inspection",
                "requested_ttl_seconds": 600,
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert set(payload) == {"request", "lease", "warnings"}
        assert payload["lease"]["lease_id"]
        assert payload["lease"]["capability"] == "networking.firewall.inspect"
        assert payload["lease"]["single_use"] is True
        assert "secret" not in str(payload).lower()
        assert "value" not in payload["lease"]
    finally:
        app.dependency_overrides.pop(get_keys_service_user, None)


def test_capability_lease_binds_parameters_is_single_use_and_audits_safely(
    test_app, db
) -> None:
    app.dependency_overrides[get_keys_service_user] = _keys_service_override(db)
    try:
        _setup_capability(
            test_app,
            name="networking.firewall.inspect-lease",
            host_id="norman",
        )
        request = test_app.post(
            "/v1/capabilities/request",
            headers={"X-Norman-Keys-Host-Fingerprint": FINGERPRINT},
            json={
                "capability": "networking.firewall.inspect-lease",
                "host_id": "norman",
                "identity_fingerprint": FINGERPRINT,
                "requester_type": "agent",
                "requester_id": "hal-tui",
                "lane": "personal",
                "action": "inspect",
                "parameters": {"scope": "dhcp", "sensitive": "must-not-audit"},
                "target_host": "firewall.home.arpa",
            },
        )
        assert request.status_code == 200, request.text
        lease_id = request.json()["lease"]["lease_id"]

        mismatch = test_app.post(
            f"/v1/capabilities/{lease_id}/invoke",
            headers={"X-Norman-Keys-Host-Fingerprint": FINGERPRINT},
            json={
                "host_id": "norman",
                "identity_fingerprint": FINGERPRINT,
                "parameters": {"scope": "interfaces"},
            },
        )
        assert mismatch.status_code == 403

        invoked = test_app.post(
            f"/v1/capabilities/{lease_id}/invoke",
            headers={"X-Norman-Keys-Host-Fingerprint": FINGERPRINT},
            json={
                "host_id": "norman",
                "identity_fingerprint": FINGERPRINT,
                "parameters": {"scope": "dhcp", "sensitive": "must-not-audit"},
            },
        )
        assert invoked.status_code == 200, invoked.text
        assert invoked.json()["status"] == "completed"
        assert "secret" not in invoked.text.lower()

        replay = test_app.post(
            f"/v1/capabilities/{lease_id}/invoke",
            headers={"X-Norman-Keys-Host-Fingerprint": FINGERPRINT},
            json={
                "host_id": "norman",
                "identity_fingerprint": FINGERPRINT,
                "parameters": {"scope": "dhcp", "sensitive": "must-not-audit"},
            },
        )
        assert replay.status_code == 409

        audit = test_app.get("/api/v1/keys/capability-audit")
        assert audit.status_code == 200
        entries = audit.json()
        requested = next(
            item for item in entries if item["event_type"] == "capability_requested"
        )
        assert requested["metadata_json"]["parameter_count"] == 2
        assert "scope" not in str(entries)
        assert "must-not-audit" not in str(entries)
        assert {item["event_type"] for item in entries} >= {
            "capability_requested",
            "capability_issued",
            "capability_completed",
        }
    finally:
        app.dependency_overrides.pop(get_keys_service_user, None)
