from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.models import (
    SecretAlias,
    SecretLease,
    SecretPolicy,
    SecretProvider,
    SecretStashItem,
)
from app.services.secret_keys import resolve_secret_stash_item


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
):
    policy = SecretPolicy(
        name=name,
        requester_type="agent",
        requester_id="norman-prime",
        lane="shared_infra",
        secret_prefix="networking/",
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


def test_keys_rejects_unknown_request_mode_before_lookup(test_app):
    response = test_app.post(
        "/api/v1/keys/requests",
        json={"name": "networking/missing", "requested_mode": "debug"},
    )

    assert response.status_code == 422


def test_keys_read_mode_requires_policy_and_alias_raw_reveal(test_app, db, tmp_path):
    _, alias = _seed_file_alias(db, tmp_path, suffix="-blocked-read")
    _seed_policy(
        db,
        name="networking-blocked-read",
        approval_required=False,
        raw_reveal_allowed=False,
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
            "reason": "attempt raw read",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Raw secret reveal is not allowed"


def test_keys_stash_returns_pointer_without_secret_and_resolves_internally(
    test_app, db
):
    raw_value = "raw-token-value-123"

    response = test_app.post(
        "/api/v1/keys/stash",
        json={
            "value": raw_value,
            "label": "api credential",
            "source": "manual",
            "ttl_seconds": 900,
        },
    )

    assert response.status_code == 200
    assert raw_value not in response.text
    payload = response.json()
    assert payload["pointer_token"].startswith("sec_")
    assert payload["pointer_uri"] == f"secret://stash/{payload['pointer_token']}"
    assert payload["masked_preview"] == "19 chars, 1 line"

    item = (
        db.query(SecretStashItem)
        .filter(SecretStashItem.pointer_token == payload["pointer_token"])
        .first()
    )
    assert item is not None
    assert item.encrypted_value != raw_value
    assert raw_value not in item.encrypted_value

    resolved = resolve_secret_stash_item(
        db,
        pointer_token=payload["pointer_token"],
        user_id=payload["user_id"],
        requester_type="agent",
        requester_id="norman-prime",
        reason="unit test",
    )

    assert resolved == raw_value
    db.expire_all()
    item = (
        db.query(SecretStashItem)
        .filter(SecretStashItem.pointer_token == payload["pointer_token"])
        .first()
    )
    assert item.last_used_at is not None


def test_keys_stash_list_and_revoke_do_not_reveal_secret(test_app, db):
    raw_value = "another-raw-token"
    create_response = test_app.post(
        "/api/v1/keys/stash",
        json={
            "value": raw_value,
            "label": "temporary token",
            "source": "manual",
            "ttl_seconds": 900,
        },
    )
    payload = create_response.json()

    list_response = test_app.get("/api/v1/keys/stash")

    assert list_response.status_code == 200
    assert raw_value not in list_response.text
    assert any(
        item["pointer_token"] == payload["pointer_token"]
        for item in list_response.json()
    )

    revoke_response = test_app.post(
        f"/api/v1/keys/stash/{payload['pointer_token']}/revoke"
    )

    assert revoke_response.status_code == 200
    assert raw_value not in revoke_response.text
    assert revoke_response.json()["status"] == "revoked"
    with pytest.raises(HTTPException) as exc:
        resolve_secret_stash_item(
            db,
            pointer_token=payload["pointer_token"],
            user_id=payload["user_id"],
        )
    assert exc.value.status_code == 400


def test_keys_stash_expired_pointer_cannot_resolve(test_app, db):
    raw_value = "expiring-raw-token"
    create_response = test_app.post(
        "/api/v1/keys/stash",
        json={
            "value": raw_value,
            "label": "expiring token",
            "source": "manual",
            "ttl_seconds": 900,
        },
    )
    payload = create_response.json()
    item = (
        db.query(SecretStashItem)
        .filter(SecretStashItem.pointer_token == payload["pointer_token"])
        .first()
    )
    item.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        resolve_secret_stash_item(
            db,
            pointer_token=payload["pointer_token"],
            user_id=payload["user_id"],
        )

    assert exc.value.status_code == 410
    db.expire_all()
    item = (
        db.query(SecretStashItem)
        .filter(SecretStashItem.pointer_token == payload["pointer_token"])
        .first()
    )
    assert item.status == "expired"
