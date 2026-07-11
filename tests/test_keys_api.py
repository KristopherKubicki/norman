from __future__ import annotations

from pathlib import Path

from app.api.deps import get_current_user, get_keys_service_user
from app.core.config import settings
from app.crud.user import create_user, get_user_by_email
from app.main import app
from app.models import SecretAlias, SecretLease, SecretPolicy, SecretProvider
from app.schemas.user import UserCreate


def _seed_file_alias(
    db, tmp_path: Path, *, name: str = "networking/prox_root", suffix: str = ""
):
    secret_file = tmp_path / "prox_root.txt"
    secret_file.write_text("super-secret-value\n", encoding="utf-8")
    provider = SecretProvider(
        name=f"local-file{suffix}", kind="file", enabled=True, config={}
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    alias = SecretAlias(
        name=f"{name}{suffix}",
        provider_id=provider.id,
        backend_ref=str(secret_file),
        lane="shared_infra",
        enabled=True,
        default_ttl_seconds=900,
        allow_raw_reveal=True,
    )
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return provider, alias


def _seed_policy(
    db,
    *,
    name: str,
    approval_required: bool,
    raw_reveal_allowed: bool,
    allowed_modes: list[str],
    secret_prefix: str = "networking/",
    requester_id: str = "norman-prime",
):
    policy = SecretPolicy(
        name=name,
        requester_type="agent",
        requester_id=requester_id,
        lane="shared_infra",
        secret_prefix=secret_prefix,
        allowed_modes=allowed_modes,
        max_ttl_seconds=900,
        approval_required=approval_required,
        raw_reveal_allowed=raw_reveal_allowed,
        enabled=True,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


def _seed_env_file_alias(db, tmp_path: Path, *, name: str = "norman/runtime-token"):
    env_file = tmp_path / "runtime.env"
    env_file.write_text(
        '# runtime bridge\nCONSOLE_RUNTIME_SERVICE_TOKEN="brokered-token"\n',
        encoding="utf-8",
    )
    provider = SecretProvider(
        name=f"runtime-env-{name.replace('/', '-')}",
        kind="env_file",
        enabled=True,
        config={"path": str(env_file)},
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    alias = SecretAlias(
        name=name,
        provider_id=provider.id,
        backend_ref="CONSOLE_RUNTIME_SERVICE_TOKEN",
        lane="shared_infra",
        enabled=True,
        default_ttl_seconds=900,
        allow_raw_reveal=True,
    )
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return provider, alias


def test_keys_request_pending_when_policy_requires_approval(test_app, db, tmp_path):
    _, alias = _seed_file_alias(db, tmp_path, suffix="-pending")
    _seed_policy(
        db,
        name="networking-pending",
        approval_required=True,
        raw_reveal_allowed=False,
        allowed_modes=["inject", "read"],
    )

    response = test_app.post(
        "/api/v1/keys/requests",
        json={
            "name": alias.name,
            "requested_mode": "inject",
            "requester_type": "agent",
            "requester_id": "norman-prime",
            "lane": "shared_infra",
            "reason": "ssh proxmox",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request"]["status"] == "pending"
    assert payload["request"]["approval_required"] is True
    assert payload["lease"] is None
    assert payload["secret"] is None


def test_keys_request_can_issue_immediately_and_return_secret(test_app, db, tmp_path):
    _, alias = _seed_file_alias(db, tmp_path, suffix="-immediate")
    _seed_policy(
        db,
        name="networking-immediate",
        approval_required=False,
        raw_reveal_allowed=True,
        allowed_modes=["read"],
    )

    response = test_app.post(
        "/api/v1/keys/requests",
        json={
            "name": alias.name,
            "requested_mode": "read",
            "requester_type": "agent",
            "requester_id": "norman-prime",
            "lane": "shared_infra",
            "reason": "show secret for migration",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request"]["status"] == "issued"
    assert payload["lease"]["status"] == "active"
    assert payload["secret"] == "super-secret-value"
    assert payload["value"] == "super-secret-value"


def test_keys_approve_pending_request_issues_lease(test_app, db, tmp_path):
    _, alias = _seed_file_alias(db, tmp_path, suffix="-review")
    _seed_policy(
        db,
        name="networking-review",
        approval_required=True,
        raw_reveal_allowed=True,
        allowed_modes=["read"],
    )

    request_response = test_app.post(
        "/api/v1/keys/requests",
        json={
            "name": alias.name,
            "requested_mode": "read",
            "requester_type": "agent",
            "requester_id": "norman-prime",
            "lane": "shared_infra",
            "reason": "review current root password",
        },
    )
    request_payload = request_response.json()

    response = test_app.post(
        f"/api/v1/keys/requests/{request_payload['request']['id']}/approve",
        json={"reason": "approved"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request"]["status"] == "issued"
    assert payload["lease"]["status"] == "active"
    assert payload["secret"] == "super-secret-value"


def test_keys_active_leases_and_revoke(test_app, db, tmp_path):
    _, alias = _seed_file_alias(db, tmp_path, suffix="-active")
    _seed_policy(
        db,
        name="networking-active",
        approval_required=False,
        raw_reveal_allowed=True,
        allowed_modes=["read"],
    )

    response = test_app.post(
        "/api/v1/keys/requests",
        json={
            "name": alias.name,
            "requested_mode": "read",
            "requester_type": "agent",
            "requester_id": "norman-prime",
            "lane": "shared_infra",
        },
    )
    payload = response.json()
    lease_id = payload["lease"]["id"]

    active = test_app.get("/api/v1/keys/leases/active")
    assert active.status_code == 200
    assert any(item["id"] == lease_id for item in active.json())

    revoked = test_app.post(f"/api/v1/keys/leases/{lease_id}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    db.expire_all()
    lease = db.query(SecretLease).filter(SecretLease.id == lease_id).first()
    assert lease is not None
    assert lease.status == "revoked"


def test_env_file_provider_can_issue_secret(test_app, db, tmp_path):
    _, alias = _seed_env_file_alias(db, tmp_path, name="norman/env-provider")
    _seed_policy(
        db,
        name="runtime-env-provider",
        approval_required=False,
        raw_reveal_allowed=True,
        allowed_modes=["read"],
        secret_prefix="norman/",
    )

    response = test_app.post(
        "/api/v1/keys/requests",
        json={
            "name": alias.name,
            "requested_mode": "read",
            "requester_type": "agent",
            "requester_id": "norman-prime",
            "lane": "shared_infra",
            "reason": "runtime token lookup",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "env_file"
    assert payload["lease"]["provider_lease_id"].endswith(
        "#CONSOLE_RUNTIME_SERVICE_TOKEN"
    )
    assert payload["value"] == "brokered-token"


def test_environment_provider_can_issue_secret(test_app, db, monkeypatch):
    monkeypatch.setenv("CONSOLE_RUNTIME_SERVICE_TOKEN", "env-runtime-token")
    provider = SecretProvider(name="runtime-env", kind="env", enabled=True, config={})
    db.add(provider)
    db.commit()
    db.refresh(provider)
    alias = SecretAlias(
        name="norman/env-runtime-token",
        provider_id=provider.id,
        backend_ref="CONSOLE_RUNTIME_SERVICE_TOKEN",
        lane="shared_infra",
        enabled=True,
        default_ttl_seconds=900,
        allow_raw_reveal=True,
    )
    db.add(alias)
    db.commit()
    db.refresh(alias)
    _seed_policy(
        db,
        name="runtime-env-service-provider",
        approval_required=False,
        raw_reveal_allowed=True,
        allowed_modes=["read"],
        secret_prefix="norman/",
    )

    response = test_app.post(
        "/api/v1/keys/requests",
        json={
            "name": alias.name,
            "requested_mode": "read",
            "requester_type": "agent",
            "requester_id": "norman-prime",
            "lane": "shared_infra",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "env"
    assert payload["lease"]["provider_lease_id"] == "env:CONSOLE_RUNTIME_SERVICE_TOKEN"
    assert payload["value"] == "env-runtime-token"


def test_compat_secret_get_requires_service_token_and_returns_value(
    test_app, db, tmp_path
):
    previous_token = settings.norman_keys_service_token
    previous_email = settings.norman_keys_service_user_email
    saved_current_override = app.dependency_overrides.pop(get_current_user, None)
    saved_keys_override = app.dependency_overrides.pop(get_keys_service_user, None)
    settings.norman_keys_service_token = "keys-service-token"
    settings.norman_keys_service_user_email = "keys@example.com"
    try:
        if not get_user_by_email(db, email="keys@example.com"):
            create_user(
                db,
                UserCreate(
                    email="keys@example.com",
                    username="keys_user",
                    password="pass123",
                ),
            )
        _, alias = _seed_env_file_alias(db, tmp_path, name="norman/runtime-token")
        _seed_policy(
            db,
            name="runtime-compat",
            approval_required=False,
            raw_reveal_allowed=True,
            allowed_modes=["read"],
            secret_prefix="norman/",
            requester_id="runtime-tui-bridge",
        )

        missing = test_app.post("/v1/secrets/get", json={"name": alias.name})
        assert missing.status_code == 401

        wrong = test_app.post(
            "/v1/secrets/get",
            headers={"Authorization": "Bearer wrong-token"},
            json={"name": alias.name},
        )
        assert wrong.status_code == 401

        response = test_app.post(
            "/v1/secrets/get",
            headers={"Authorization": "Bearer keys-service-token"},
            json={"name": alias.name},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["value"] == "brokered-token"
        assert payload["secret"] == "brokered-token"
        assert payload["lease_id"]
        assert payload["request_id"]
        assert payload["provider"] == "env_file"
    finally:
        settings.norman_keys_service_token = previous_token
        settings.norman_keys_service_user_email = previous_email
        if saved_current_override is not None:
            app.dependency_overrides[get_current_user] = saved_current_override
        if saved_keys_override is not None:
            app.dependency_overrides[get_keys_service_user] = saved_keys_override
