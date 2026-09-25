from __future__ import annotations
import pytest

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


@pytest.fixture
def aws_lease(test_app, db, monkeypatch):
    """Create a real broker lease with mocked AWS only at execution."""
    from app.models import KeysCapability

    monkeypatch.setenv("NORMAN_KEYS_AWS_EXECUTOR_ENABLED", "1")
    app.dependency_overrides[get_keys_service_user] = _keys_service_override(db)
    import uuid

    host = "aws-host-" + uuid.uuid4().hex
    name = "aws.inspect." + uuid.uuid4().hex
    _setup_capability(test_app, name=name, host_id=host)
    capability = db.query(KeysCapability).filter_by(name=name).one()
    capability.executor_kind = "aws-readiness-v1"
    capability.executor_ref = "104637383649"
    db.commit()
    parameters = {"account_id": "104637383649"}
    response = test_app.post(
        "/v1/capabilities/request",
        headers={"X-Norman-Keys-Host-Fingerprint": FINGERPRINT},
        json={
            "capability": capability.name,
            "host_id": host,
            "identity_fingerprint": FINGERPRINT,
            "requester_type": "agent",
            "requester_id": "hal-tui",
            "lane": "personal",
            "action": "inspect",
            "parameters": parameters,
            "target_host": "firewall.home.arpa",
        },
    )
    assert response.status_code == 200, response.text
    lease_id = response.json()["lease"]["lease_id"]

    def invoke():
        return test_app.post(
            f"/v1/capabilities/{lease_id}/invoke",
            headers={"X-Norman-Keys-Host-Fingerprint": FINGERPRINT},
            json={
                "host_id": host,
                "identity_fingerprint": FINGERPRINT,
                "parameters": parameters,
            },
        )

    try:
        yield invoke, lease_id, capability.id, host
    finally:
        app.dependency_overrides.pop(get_keys_service_user, None)


def test_aws_dispatch_returns_typed_receipt_and_rejects_replay(aws_lease, monkeypatch):
    from unittest.mock import Mock
    from app.services import aws_keys_readiness

    execute = Mock(
        return_value={
            "account_id": "104637383649",
            "identity_verified": True,
            "root_mfa_enabled": True,
            "unexpected": "must-not-return",
        }
    )
    monkeypatch.setattr(aws_keys_readiness, "execute_readiness", execute)
    response = aws_lease[0]()
    assert response.status_code == 200, response.text
    assert response.json()["result"] == {
        "account_id": "104637383649",
        "identity_verified": True,
        "root_mfa_enabled": True,
    }
    assert "must-not-return" not in response.text
    assert aws_lease[0]().status_code == 409
    assert execute.call_count == 1


@pytest.mark.parametrize(
    "revocation",
    ["capability", "policy", "action", "target", "requester", "approval", "enrollment"],
)
def test_post_issue_revocation_prevents_aws(aws_lease, db, monkeypatch, revocation):
    from unittest.mock import Mock
    from app.models import KeysCapability, KeysCapabilityPolicy, KeysHostEnrollment
    from app.services import aws_keys_readiness

    capability = db.get(KeysCapability, aws_lease[2])
    policy = db.query(KeysCapabilityPolicy).filter_by(capability_id=capability.id).one()
    enrollment = db.query(KeysHostEnrollment).filter_by(host_id=aws_lease[3]).one()
    if revocation == "capability":
        capability.enabled = False
    elif revocation == "policy":
        policy.enabled = False
    elif revocation == "action":
        policy.allowed_actions = ["different"]
    elif revocation == "target":
        policy.allowed_target_hosts = ["different"]
    elif revocation == "requester":
        policy.requester_id = "different"
    elif revocation == "approval":
        policy.approval_required = True
    else:
        enrollment.capability_names = ["different"]
    db.commit()
    execute = Mock()
    monkeypatch.setattr(aws_keys_readiness, "execute_readiness", execute)
    assert aws_lease[0]().status_code == 403
    execute.assert_not_called()


def test_failed_aws_check_is_consumed_and_audited(aws_lease, test_app, monkeypatch):
    from app.services import aws_keys_readiness

    def fail(**kwargs):
        raise aws_keys_readiness.AWSReadinessError("private-detail")

    monkeypatch.setattr(aws_keys_readiness, "execute_readiness", fail)
    response = aws_lease[0]()
    assert response.status_code == 502
    assert "private-detail" not in response.text
    assert aws_lease[0]().status_code == 409
    audit = test_app.get("/api/v1/keys/capability-audit").json()
    assert any(item["event_type"] == "capability_failed" for item in audit)
    assert "private-detail" not in str(audit)


def test_claim_rejects_stale_active_lease(aws_lease, db):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.models import KeysCapabilityLease
    from app.services.secret_keys import _claim_capability_lease

    lease = db.query(KeysCapabilityLease).filter_by(lease_uuid=aws_lease[1]).one()
    stale = SimpleNamespace(id=lease.id, single_use=True)
    _claim_capability_lease(db, lease=lease, receipt_uuid="first")
    with pytest.raises(HTTPException) as error:
        _claim_capability_lease(db, lease=stale, receipt_uuid="second")
    assert error.value.status_code == 409


def test_aws_executor_is_disabled_by_default(aws_lease, monkeypatch):
    from unittest.mock import Mock
    from app.services import aws_keys_readiness

    monkeypatch.delenv("NORMAN_KEYS_AWS_EXECUTOR_ENABLED", raising=False)
    execute = Mock()
    monkeypatch.setattr(aws_keys_readiness, "execute_readiness", execute)
    assert aws_lease[0]().status_code == 503
    execute.assert_not_called()
