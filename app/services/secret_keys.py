from __future__ import annotations

import subprocess
import uuid
import secrets as py_secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import crud
from app.core.encryption import EncryptionManager
from app.models import (
    SecretAlias,
    SecretLease,
    SecretPolicy,
    SecretRequest,
    SecretStashItem,
)
from app.schemas.secret_keys import SecretRequestCreate, SecretStashCreate


@dataclass
class ProviderLeaseResult:
    value: Optional[str]
    provider_lease_id: str
    renewable: bool


class SecretProviderBase:
    def __init__(self, *, config: Optional[dict] = None) -> None:
        self.config = config or {}

    def describe_secret(self, backend_ref: str) -> dict:
        return {"backend_ref": backend_ref}

    def get_secret(
        self, backend_ref: str, *, subject: str, ttl_seconds: int
    ) -> ProviderLeaseResult:
        raise NotImplementedError

    def renew_lease(self, provider_lease_id: str, ttl_seconds: int) -> str:
        return provider_lease_id

    def revoke_lease(self, provider_lease_id: str) -> None:
        return None


class FileSecretProvider(SecretProviderBase):
    def get_secret(
        self, backend_ref: str, *, subject: str, ttl_seconds: int
    ) -> ProviderLeaseResult:
        base_dir = (self.config or {}).get("base_dir", "")
        path = Path(backend_ref)
        if not path.is_absolute() and base_dir:
            path = Path(base_dir) / backend_ref
        value = path.read_text(encoding="utf-8").strip()
        return ProviderLeaseResult(
            value=value,
            provider_lease_id=f"file:{path}",
            renewable=True,
        )


class CredSecretProvider(SecretProviderBase):
    def get_secret(
        self, backend_ref: str, *, subject: str, ttl_seconds: int
    ) -> ProviderLeaseResult:
        cmd = ["cred", "get", backend_ref]
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        return ProviderLeaseResult(
            value=result.stdout.strip(),
            provider_lease_id=f"cred:{backend_ref}",
            renewable=True,
        )


def _build_provider(kind: str, config: Optional[dict]) -> SecretProviderBase:
    if kind == "file":
        return FileSecretProvider(config=config)
    if kind == "cred":
        return CredSecretProvider(config=config)
    raise HTTPException(status_code=400, detail=f"Unsupported secret provider: {kind}")


def _mask_stash_value(value: str) -> str:
    line_count = value.count("\n") + 1 if value else 0
    suffix = "line" if line_count == 1 else "lines"
    return f"{len(value)} chars, {line_count} {suffix}"


def _generate_stash_pointer() -> str:
    return f"sec_{py_secrets.token_urlsafe(24)}"


def _get_encryption_manager() -> EncryptionManager:
    return EncryptionManager()


def _policy_score(
    policy: SecretPolicy, body: SecretRequestCreate, alias: SecretAlias
) -> int:
    score = len(policy.secret_prefix or "")
    if policy.requester_type == body.requester_type:
        score += 20
    elif policy.requester_type != "*":
        return -1
    if policy.requester_id:
        if policy.requester_id != body.requester_id:
            return -1
        score += 10
    if policy.lane:
        effective_lane = body.lane or alias.lane
        if policy.lane != effective_lane:
            return -1
        score += 10
    return score


def _match_policy(
    db: Session, *, alias: SecretAlias, body: SecretRequestCreate
) -> Optional[SecretPolicy]:
    matches: list[tuple[int, SecretPolicy]] = []
    for policy in crud.secret_keys.list_policies(db):
        if not alias.name.startswith(policy.secret_prefix):
            continue
        score = _policy_score(policy, body, alias)
        if score >= 0:
            matches.append((score, policy))
    if not matches:
        return None
    matches.sort(key=lambda item: (item[0], item[1].id), reverse=True)
    return matches[0][1]


def _issue_lease(
    db: Session,
    *,
    request: SecretRequest,
    alias: SecretAlias,
    provider_kind: str,
    provider_config: Optional[dict],
    ttl_seconds: int,
) -> tuple[SecretLease, Optional[str]]:
    provider = _build_provider(provider_kind, provider_config)
    result = provider.get_secret(
        alias.backend_ref,
        subject=request.requester_id,
        ttl_seconds=ttl_seconds,
    )
    lease = crud.secret_keys.create_lease(
        db,
        lease_uuid=str(uuid.uuid4()),
        request_id=request.id,
        provider_id=alias.provider_id,
        provider_lease_id=result.provider_lease_id,
        secret_alias=alias.name,
        granted_mode=request.requested_mode,
        granted_ttl_seconds=ttl_seconds,
        renewable=result.renewable,
        status="active",
        issued_to=request.requester_id,
        expires_at=datetime.utcnow() + timedelta(seconds=ttl_seconds),
    )
    crud.secret_keys.create_audit_event(
        db,
        user_id=request.user_id,
        request_id=request.id,
        lease_id=lease.id,
        event_type="lease_issued",
        actor_type="system",
        actor_id="norman-keys",
        summary=f"Issued {alias.name} lease to {request.requester_id}",
        metadata_json={"mode": request.requested_mode, "ttl_seconds": ttl_seconds},
    )
    return lease, result.value


def create_secret_request(
    db: Session,
    *,
    user_id: int,
    body: SecretRequestCreate,
) -> tuple[SecretRequest, Optional[SecretLease], Optional[str], str, list[str]]:
    alias = crud.secret_keys.get_alias(db, name=body.name)
    if not alias:
        raise HTTPException(status_code=404, detail="Secret alias not found")
    provider = crud.secret_keys.get_provider(db, provider_id=alias.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Secret provider not found")
    policy = _match_policy(db, alias=alias, body=body)
    if not policy:
        raise HTTPException(status_code=403, detail="No secret policy matched request")
    if body.requested_mode not in (policy.allowed_modes or []):
        raise HTTPException(status_code=403, detail="Requested mode blocked by policy")
    if body.requested_mode == "read" and not (
        policy.raw_reveal_allowed and alias.allow_raw_reveal
    ):
        raise HTTPException(status_code=403, detail="Raw secret reveal is not allowed")
    ttl_seconds = min(body.requested_ttl_seconds, policy.max_ttl_seconds)
    request = crud.secret_keys.create_request(
        db,
        user_id=user_id,
        request_uuid=str(uuid.uuid4()),
        requester_type=body.requester_type,
        requester_id=body.requester_id,
        session_id=body.session_id,
        secret_alias=alias.name,
        requested_mode=body.requested_mode,
        requested_ttl_seconds=ttl_seconds,
        lane=body.lane or alias.lane,
        intent=body.intent,
        reason=body.reason,
        target_host=body.target_host,
        status="pending" if policy.approval_required else "issued",
        policy_id=policy.id,
        approval_required=policy.approval_required,
        approval_reason="approval required" if policy.approval_required else "",
    )
    crud.secret_keys.create_audit_event(
        db,
        user_id=user_id,
        request_id=request.id,
        lease_id=None,
        event_type="requested",
        actor_type=body.requester_type,
        actor_id=body.requester_id,
        summary=f"Requested {alias.name} via {body.requested_mode}",
        metadata_json={
            "target_host": body.target_host,
            "lane": body.lane or alias.lane,
        },
    )
    warnings: list[str] = []
    if policy.approval_required:
        return request, None, None, provider.kind, warnings
    lease, secret_value = _issue_lease(
        db,
        request=request,
        alias=alias,
        provider_kind=provider.kind,
        provider_config=provider.config,
        ttl_seconds=ttl_seconds,
    )
    return request, lease, secret_value, provider.kind, warnings


def approve_secret_request(
    db: Session,
    *,
    request_id: int,
    decided_by: int,
    reason: str = "",
    ttl_override_seconds: Optional[int] = None,
) -> tuple[SecretRequest, Optional[SecretLease], Optional[str], str]:
    request = crud.secret_keys.get_request(db, request_id=request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Secret request not found")
    if request.status != "pending":
        raise HTTPException(status_code=400, detail="Secret request is not pending")
    alias = crud.secret_keys.get_alias(db, name=request.secret_alias)
    if not alias:
        raise HTTPException(status_code=404, detail="Secret alias not found")
    provider = crud.secret_keys.get_provider(db, provider_id=alias.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Secret provider not found")
    ttl_seconds = min(
        ttl_override_seconds or request.requested_ttl_seconds,
        request.requested_ttl_seconds,
    )
    request = crud.secret_keys.decide_request(
        db,
        request=request,
        status="issued",
        decided_by=decided_by,
        approval_reason=reason or "approved",
    )
    lease, secret_value = _issue_lease(
        db,
        request=request,
        alias=alias,
        provider_kind=provider.kind,
        provider_config=provider.config,
        ttl_seconds=ttl_seconds,
    )
    return request, lease, secret_value, provider.kind


def reject_secret_request(
    db: Session, *, request_id: int, decided_by: int, reason: str = ""
) -> SecretRequest:
    request = crud.secret_keys.get_request(db, request_id=request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Secret request not found")
    if request.status != "pending":
        raise HTTPException(status_code=400, detail="Secret request is not pending")
    request = crud.secret_keys.decide_request(
        db,
        request=request,
        status="rejected",
        decided_by=decided_by,
        approval_reason=reason or "rejected",
    )
    crud.secret_keys.create_audit_event(
        db,
        user_id=request.user_id,
        request_id=request.id,
        lease_id=None,
        event_type="rejected",
        actor_type="operator",
        actor_id=str(decided_by),
        summary=f"Rejected secret request for {request.secret_alias}",
        metadata_json={"reason": reason or "rejected"},
    )
    return request


def renew_secret_lease(
    db: Session, *, lease_id: int, ttl_seconds: int, actor_id: int
) -> SecretLease:
    lease = crud.secret_keys.get_lease(db, lease_id=lease_id)
    if not lease:
        raise HTTPException(status_code=404, detail="Secret lease not found")
    if lease.status != "active":
        raise HTTPException(status_code=400, detail="Secret lease is not active")
    lease = crud.secret_keys.update_lease(
        db,
        lease=lease,
        expires_at=datetime.utcnow() + timedelta(seconds=ttl_seconds),
    )
    crud.secret_keys.create_audit_event(
        db,
        user_id=None,
        request_id=lease.request_id,
        lease_id=lease.id,
        event_type="renewed",
        actor_type="operator",
        actor_id=str(actor_id),
        summary=f"Renewed lease for {lease.secret_alias}",
        metadata_json={"ttl_seconds": ttl_seconds},
    )
    return lease


def revoke_secret_lease(db: Session, *, lease_id: int, actor_id: int) -> SecretLease:
    lease = crud.secret_keys.get_lease(db, lease_id=lease_id)
    if not lease:
        raise HTTPException(status_code=404, detail="Secret lease not found")
    if lease.status == "revoked":
        return lease
    lease = crud.secret_keys.update_lease(
        db,
        lease=lease,
        status="revoked",
        revoked_by=actor_id,
    )
    crud.secret_keys.create_audit_event(
        db,
        user_id=None,
        request_id=lease.request_id,
        lease_id=lease.id,
        event_type="revoked",
        actor_type="operator",
        actor_id=str(actor_id),
        summary=f"Revoked lease for {lease.secret_alias}",
        metadata_json={},
    )
    return lease


def create_secret_stash_item(
    db: Session,
    *,
    user_id: int,
    body: SecretStashCreate,
) -> SecretStashItem:
    encrypted_value = _get_encryption_manager().encrypt(body.value)
    item = crud.secret_keys.create_stash_item(
        db,
        pointer_token=_generate_stash_pointer(),
        user_id=user_id,
        channel_id=body.channel_id,
        label=body.label,
        encrypted_value=encrypted_value,
        masked_preview=_mask_stash_value(body.value),
        source=body.source,
        expires_at=datetime.utcnow() + timedelta(seconds=body.ttl_seconds),
    )
    crud.secret_keys.create_audit_event(
        db,
        user_id=user_id,
        request_id=None,
        lease_id=None,
        event_type="stash_created",
        actor_type="operator",
        actor_id=str(user_id),
        summary="Created secret stash pointer",
        metadata_json={
            "pointer_token": item.pointer_token,
            "channel_id": body.channel_id,
            "source": body.source,
            "ttl_seconds": body.ttl_seconds,
        },
    )
    return item


def list_secret_stash_items(
    db: Session, *, user_id: int, limit: int = 100
) -> list[SecretStashItem]:
    return crud.secret_keys.list_active_stash_items(db, user_id=user_id, limit=limit)


def resolve_secret_stash_item(
    db: Session,
    *,
    pointer_token: str,
    user_id: int,
    requester_type: str = "agent",
    requester_id: str = "norman-prime",
    reason: str = "",
) -> str:
    item = crud.secret_keys.get_stash_item(db, pointer_token=pointer_token)
    if not item or item.user_id != user_id:
        raise HTTPException(status_code=404, detail="Secret stash pointer not found")
    if item.status != "active":
        raise HTTPException(
            status_code=400, detail="Secret stash pointer is not active"
        )
    now = datetime.utcnow()
    if item.expires_at <= now:
        crud.secret_keys.update_stash_item(db, item=item, status="expired")
        raise HTTPException(status_code=410, detail="Secret stash pointer expired")
    value = _get_encryption_manager().decrypt(item.encrypted_value)
    crud.secret_keys.update_stash_item(db, item=item, last_used_at=now)
    crud.secret_keys.create_audit_event(
        db,
        user_id=user_id,
        request_id=None,
        lease_id=None,
        event_type="stash_resolved",
        actor_type=requester_type,
        actor_id=requester_id,
        summary="Resolved secret stash pointer",
        metadata_json={
            "pointer_token": pointer_token,
            "channel_id": item.channel_id,
            "reason": reason,
        },
    )
    return value


def revoke_secret_stash_item(
    db: Session, *, pointer_token: str, user_id: int
) -> SecretStashItem:
    item = crud.secret_keys.get_stash_item(db, pointer_token=pointer_token)
    if not item or item.user_id != user_id:
        raise HTTPException(status_code=404, detail="Secret stash pointer not found")
    if item.status == "revoked":
        return item
    item = crud.secret_keys.update_stash_item(
        db,
        item=item,
        status="revoked",
        revoked_by=user_id,
    )
    crud.secret_keys.create_audit_event(
        db,
        user_id=user_id,
        request_id=None,
        lease_id=None,
        event_type="stash_revoked",
        actor_type="operator",
        actor_id=str(user_id),
        summary="Revoked secret stash pointer",
        metadata_json={"pointer_token": pointer_token},
    )
    return item
