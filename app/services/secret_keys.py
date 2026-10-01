from __future__ import annotations

import os
import subprocess
import secrets
import shlex
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import crud
from app.core.encryption import EncryptionManager
from app.models import SecretAlias, SecretLease, SecretPolicy, SecretRequest
from app.schemas.secret_keys import SecretRequestCreate, SecretStashCreate


@dataclass
class ProviderLeaseResult:
    value: Optional[str]
    provider_lease_id: str
    renewable: bool


SECRET_STASH_POINTER_PREFIX = "norman-secret://stash/"


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


def _parse_env_file_value(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""
    try:
        parts = shlex.split(f"x={value}", comments=True, posix=True)
    except ValueError:
        return value.strip("'\"")
    if not parts:
        return ""
    parsed = parts[0]
    if parsed.startswith("x="):
        return parsed[2:]
    return value.strip("'\"")


class EnvFileSecretProvider(SecretProviderBase):
    def get_secret(
        self, backend_ref: str, *, subject: str, ttl_seconds: int
    ) -> ProviderLeaseResult:
        path_value = str((self.config or {}).get("path") or "").strip()
        key = str(backend_ref or "").strip()
        if "@" in key:
            key, path_value = key.split("@", 1)
            key = key.strip()
            path_value = path_value.strip()
        if not path_value:
            raise HTTPException(
                status_code=400, detail="Env-file secret provider path is not set"
            )
        if not key:
            raise HTTPException(
                status_code=400, detail="Env-file secret backend ref is not set"
            )
        path = Path(path_value)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail="Env-file secret provider path was not found"
            ) from None
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("export "):
                stripped = stripped.removeprefix("export ").strip()
            name, separator, value = stripped.partition("=")
            if separator and name.strip() == key:
                return ProviderLeaseResult(
                    value=_parse_env_file_value(value),
                    provider_lease_id=f"env_file:{path}#{key}",
                    renewable=True,
                )
        raise HTTPException(status_code=404, detail="Env-file secret key was not found")


class EnvironmentSecretProvider(SecretProviderBase):
    def get_secret(
        self, backend_ref: str, *, subject: str, ttl_seconds: int
    ) -> ProviderLeaseResult:
        key = str(backend_ref or "").strip()
        if not key:
            raise HTTPException(
                status_code=400, detail="Environment secret backend ref is not set"
            )
        value = os.environ.get(key)
        if value is None:
            raise HTTPException(
                status_code=404, detail="Environment secret key was not found"
            )
        return ProviderLeaseResult(
            value=value.strip(),
            provider_lease_id=f"env:{key}",
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
        )
        return ProviderLeaseResult(
            value=result.stdout.strip(),
            provider_lease_id=f"cred:{backend_ref}",
            renewable=True,
        )


def _build_provider(kind: str, config: Optional[dict]) -> SecretProviderBase:
    if kind == "file":
        return FileSecretProvider(config=config)
    if kind == "env_file":
        return EnvFileSecretProvider(config=config)
    if kind == "env":
        return EnvironmentSecretProvider(config=config)
    if kind == "cred":
        return CredSecretProvider(config=config)
    raise HTTPException(status_code=400, detail=f"Unsupported secret provider: {kind}")


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


def _normalized_host(value: object) -> str:
    return str(value or "").strip().lower().rstrip(".")


def _host_allowed(policy: SecretPolicy, target_host: str) -> bool:
    allowed_hosts = {
        _normalized_host(host)
        for host in (policy.allowed_hosts or [])
        if _normalized_host(host)
    }
    if not allowed_hosts:
        return True
    return _normalized_host(target_host) in allowed_hosts


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
    selected = matches[0][1]
    if not _host_allowed(selected, body.target_host):
        return None
    return selected


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
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
    )
    crud.secret_keys.create_audit_event(
        db,
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
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
    )
    crud.secret_keys.create_audit_event(
        db,
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
        request_id=lease.request_id,
        lease_id=lease.id,
        event_type="revoked",
        actor_type="operator",
        actor_id=str(actor_id),
        summary=f"Revoked lease for {lease.secret_alias}",
        metadata_json={},
    )
    return lease


def _normalize_stash_label(value: str) -> str:
    text = " ".join(str(value or "").split())
    if text:
        return text[:120]
    return f"Secret {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')}"


def _normalize_stash_source(value: str) -> str:
    text = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not text:
        return "manual"
    return "".join(ch for ch in text if ch.isalnum() or ch == "_")[:32] or "manual"


def _masked_secret_preview(value: str) -> str:
    raw = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    line_count = max(1, len(raw.split("\n")))
    char_count = len(raw)
    line_label = "line" if line_count == 1 else "lines"
    char_label = "char" if char_count == 1 else "chars"
    return f"{line_count} {line_label} · {char_count} {char_label}"


def format_secret_stash_pointer(pointer_token: str) -> str:
    return f"{SECRET_STASH_POINTER_PREFIX}{pointer_token}"


def format_secret_stash_prompt_reference(*, label: str, pointer_token: str) -> str:
    pointer = format_secret_stash_pointer(pointer_token)
    return f"Secret pointer: {pointer}"


def serialize_secret_stash_item(item) -> dict:
    return {
        "id": int(item.id),
        "channel_id": int(item.channel_id) if item.channel_id is not None else None,
        "label": str(item.label or "").strip(),
        "masked_preview": str(item.masked_preview or "").strip(),
        "source": str(item.source or "").strip(),
        "status": str(item.status or "").strip(),
        "pointer": format_secret_stash_pointer(str(item.pointer_token or "").strip()),
        "prompt_reference": format_secret_stash_prompt_reference(
            label=str(item.label or "").strip() or "secret",
            pointer_token=str(item.pointer_token or "").strip(),
        ),
        "created_at": item.created_at,
        "expires_at": item.expires_at,
        "revoked_at": item.revoked_at,
    }


def create_secret_stash_item(
    db: Session,
    *,
    user_id: int,
    body: SecretStashCreate,
):
    try:
        manager = EncryptionManager()
    except Exception as exc:  # pragma: no cover - surfaced in API response
        raise HTTPException(
            status_code=503,
            detail="Secret stash is unavailable until encryption is configured.",
        ) from exc
    value = str(body.value or "")
    label = _normalize_stash_label(body.label)
    source = _normalize_stash_source(body.source)
    encrypted_value = manager.encrypt(value)
    return crud.secret_keys.create_stash_item(
        db,
        pointer_token=secrets.token_urlsafe(18),
        user_id=user_id,
        channel_id=body.channel_id,
        label=label,
        encrypted_value=encrypted_value,
        masked_preview=_masked_secret_preview(value),
        source=source,
        status="active",
        expires_at=datetime.now(UTC) + timedelta(seconds=body.ttl_seconds),
    )


def revoke_secret_stash_item(
    db: Session, *, stash_id: int, user_id: int, revoked_by: int
):
    item = crud.secret_keys.get_stash_item(db, stash_id=stash_id, user_id=user_id)
    if not item:
        raise HTTPException(status_code=404, detail="Secret stash item not found")
    if str(item.status or "").strip().lower() == "revoked":
        return item
    return crud.secret_keys.revoke_stash_item(db, item=item, revoked_by=revoked_by)


# Capability delivery deliberately does not call _build_provider(), get_secret(),
# or any compatibility secret resolver.  It authorizes a bounded action and
# returns an opaque lease for an approved server-side executor binding.
CAPABILITY_RECEIPT_EXECUTOR = "receipt"


def _canonical_capability_parameters(parameters: dict) -> str:
    import json

    return json.dumps(parameters or {}, sort_keys=True, separators=(",", ":"))


def _capability_action_hash(action: str, parameters: dict) -> str:
    import hashlib

    source = (
        f"{str(action or '').strip()}\n{_canonical_capability_parameters(parameters)}"
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _capability_summary_parameters(parameters: dict) -> dict:
    """Safe audit metadata: shape only, no user-controlled parameter values."""

    return {"parameter_count": len(parameters or {})}


def _contains_normalized(values: list | None, candidate: str) -> bool:
    normalized = {_normalized_host(value) for value in (values or []) if value}
    return _normalized_host(candidate) in normalized


def _match_capability_policy(db: Session, *, capability, body):
    matches = []
    for policy in crud.secret_keys.list_capability_policies(db, active_only=True):
        if policy.capability_id != capability.id:
            continue
        score = 0
        if policy.requester_type == body.requester_type:
            score += 20
        elif policy.requester_type != "*":
            continue
        if policy.requester_id:
            if policy.requester_id != body.requester_id:
                continue
            score += 10
        if policy.lane:
            if policy.lane != body.lane:
                continue
            score += 10
        if body.action not in (policy.allowed_actions or []):
            continue
        if policy.allowed_target_hosts and not _contains_normalized(
            policy.allowed_target_hosts, body.target_host
        ):
            continue
        matches.append((score, policy))
    if not matches:
        return None
    matches.sort(key=lambda item: (item[0], item[1].id), reverse=True)
    return matches[0][1]


def _validate_capability_enrollment(db: Session, *, body, asserted_fingerprint: str):
    from hmac import compare_digest

    enrollment = crud.secret_keys.get_host_enrollment(db, host_id=body.host_id)
    if not enrollment or enrollment.status != "active":
        raise HTTPException(
            status_code=403, detail="Host is not enrolled for Norman Keys"
        )
    if not asserted_fingerprint or not compare_digest(
        str(enrollment.identity_fingerprint), str(asserted_fingerprint)
    ):
        raise HTTPException(
            status_code=403, detail="Host identity assertion was rejected"
        )
    if not compare_digest(str(body.identity_fingerprint), str(asserted_fingerprint)):
        raise HTTPException(
            status_code=403, detail="Host identity assertion did not match request"
        )
    if enrollment.requester_ids and body.requester_id not in enrollment.requester_ids:
        raise HTTPException(
            status_code=403, detail="Requester is not enrolled on this host"
        )
    if (
        enrollment.capability_names
        and body.capability not in enrollment.capability_names
    ):
        raise HTTPException(
            status_code=403, detail="Capability is not enrolled on this host"
        )
    if enrollment.lanes and body.lane not in enrollment.lanes:
        raise HTTPException(status_code=403, detail="Lane is not enrolled on this host")
    enrollment.last_seen_at = datetime.utcnow()
    db.commit()
    db.refresh(enrollment)
    return enrollment


def _capability_lease_out(*, request, lease, capability, enrollment) -> dict:
    return {
        "lease_id": lease.lease_uuid,
        "request_id": request.request_uuid,
        "capability": capability.name,
        "host_id": enrollment.host_id,
        "action": request.action,
        "expires_at": lease.expires_at,
        "single_use": lease.single_use,
        "status": lease.status,
    }


def _issue_capability_lease(
    db: Session, *, request, capability, enrollment, ttl_seconds
):
    from app.models import KeysCapabilityLease

    lease = crud.secret_keys.create_capability_lease(
        db,
        lease_uuid=str(uuid.uuid4()),
        request_id=request.id,
        capability_id=capability.id,
        host_enrollment_id=enrollment.id,
        action_hash=request.action_hash,
        status="active",
        single_use=True,
        expires_at=datetime.utcnow() + timedelta(seconds=ttl_seconds),
    )
    crud.secret_keys.create_capability_audit_event(
        db,
        request_id=request.id,
        lease_id=lease.id,
        event_type="capability_issued",
        actor_type="system",
        actor_id="norman-keys",
        summary=f"Issued capability {capability.name} to {enrollment.host_id}",
        metadata_json={"ttl_seconds": ttl_seconds, "action": request.action},
    )
    return lease


def create_capability_request(
    db: Session,
    *,
    user_id: int,
    body,
    asserted_fingerprint: str,
):
    enrollment = _validate_capability_enrollment(
        db, body=body, asserted_fingerprint=asserted_fingerprint
    )
    capability = crud.secret_keys.get_capability(db, name=body.capability)
    if not capability:
        raise HTTPException(status_code=404, detail="Capability not found or disabled")
    policy = _match_capability_policy(db, capability=capability, body=body)
    if not policy:
        raise HTTPException(
            status_code=403, detail="No capability policy matched request"
        )
    ttl_seconds = min(body.requested_ttl_seconds, policy.max_ttl_seconds)
    action_hash = _capability_action_hash(body.action, body.parameters)
    request = crud.secret_keys.create_capability_request(
        db,
        request_uuid=str(uuid.uuid4()),
        user_id=user_id,
        host_enrollment_id=enrollment.id,
        capability_id=capability.id,
        policy_id=policy.id,
        requester_type=body.requester_type,
        requester_id=body.requester_id,
        session_id=body.session_id,
        lane=body.lane,
        action=body.action,
        action_hash=action_hash,
        target_host=body.target_host,
        reason=body.reason,
        requested_ttl_seconds=ttl_seconds,
        status="pending" if policy.approval_required else "issued",
        approval_required=policy.approval_required,
        approval_reason="approval required" if policy.approval_required else "",
    )
    crud.secret_keys.create_capability_audit_event(
        db,
        request_id=request.id,
        lease_id=None,
        event_type="capability_requested",
        actor_type=body.requester_type,
        actor_id=body.requester_id,
        summary=f"Requested capability {capability.name} action {body.action}",
        metadata_json={
            "host_id": enrollment.host_id,
            "target_host": body.target_host,
            "lane": body.lane,
            "action_hash": action_hash,
            **_capability_summary_parameters(body.parameters),
        },
    )
    if policy.approval_required:
        return request, None, capability, enrollment
    lease = _issue_capability_lease(
        db,
        request=request,
        capability=capability,
        enrollment=enrollment,
        ttl_seconds=ttl_seconds,
    )
    return request, lease, capability, enrollment


def approve_capability_request(
    db: Session,
    *,
    request_id: int,
    decided_by: int,
    reason: str,
    ttl_seconds: int | None,
):
    request = crud.secret_keys.get_capability_request(db, request_id=request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Capability request not found")
    if request.status != "pending":
        raise HTTPException(status_code=400, detail="Capability request is not pending")
    from app.models import KeysCapability, KeysHostEnrollment, KeysCapabilityPolicy

    capability = (
        db.query(KeysCapability)
        .filter(KeysCapability.id == request.capability_id)
        .first()
    )
    enrollment = (
        db.query(KeysHostEnrollment)
        .filter(KeysHostEnrollment.id == request.host_enrollment_id)
        .first()
    )
    policy = (
        db.query(KeysCapabilityPolicy)
        .filter(KeysCapabilityPolicy.id == request.policy_id)
        .first()
    )
    if (
        not capability
        or not enrollment
        or not policy
        or not capability.enabled
        or policy.enabled is not True
    ):
        raise HTTPException(
            status_code=409, detail="Capability authorization is no longer active"
        )
    request.status = "issued"
    request.decided_at = datetime.utcnow()
    request.decided_by = decided_by
    request.approval_reason = reason or "approved"
    db.commit()
    db.refresh(request)
    crud.secret_keys.create_capability_audit_event(
        db,
        request_id=request.id,
        lease_id=None,
        event_type="capability_approved",
        actor_type="operator",
        actor_id=str(decided_by),
        summary="Approved capability request",
        metadata_json={},
    )
    lease = _issue_capability_lease(
        db,
        request=request,
        capability=capability,
        enrollment=enrollment,
        ttl_seconds=min(
            ttl_seconds or request.requested_ttl_seconds, policy.max_ttl_seconds
        ),
    )
    return request, lease, capability, enrollment


def reject_capability_request(
    db: Session, *, request_id: int, decided_by: int, reason: str
):
    request = crud.secret_keys.get_capability_request(db, request_id=request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Capability request not found")
    if request.status != "pending":
        raise HTTPException(status_code=400, detail="Capability request is not pending")
    request.status = "rejected"
    request.decided_at = datetime.utcnow()
    request.decided_by = decided_by
    request.approval_reason = reason or "rejected"
    db.commit()
    db.refresh(request)
    crud.secret_keys.create_capability_audit_event(
        db,
        request_id=request.id,
        lease_id=None,
        event_type="capability_denied",
        actor_type="operator",
        actor_id=str(decided_by),
        summary="Rejected capability request",
        metadata_json={},
    )
    return request


def invoke_capability_lease(
    db: Session, *, lease_uuid: str, body, asserted_fingerprint: str
):
    from hmac import compare_digest
    from app.models import KeysCapability, KeysCapabilityRequest, KeysHostEnrollment

    lease = crud.secret_keys.get_capability_lease(db, lease_uuid=lease_uuid)
    if not lease:
        raise HTTPException(status_code=404, detail="Capability lease not found")
    request = (
        db.query(KeysCapabilityRequest)
        .filter(KeysCapabilityRequest.id == lease.request_id)
        .first()
    )
    enrollment = (
        db.query(KeysHostEnrollment)
        .filter(KeysHostEnrollment.id == lease.host_enrollment_id)
        .first()
    )
    capability = (
        db.query(KeysCapability)
        .filter(KeysCapability.id == lease.capability_id)
        .first()
    )
    if not request or not enrollment or not capability:
        raise HTTPException(status_code=409, detail="Capability lease is incomplete")
    if enrollment.host_id != body.host_id or enrollment.status != "active":
        raise HTTPException(
            status_code=403, detail="Host is not authorized for this lease"
        )
    if not asserted_fingerprint or not compare_digest(
        enrollment.identity_fingerprint, asserted_fingerprint
    ):
        raise HTTPException(
            status_code=403, detail="Host identity assertion was rejected"
        )
    if not compare_digest(body.identity_fingerprint, asserted_fingerprint):
        raise HTTPException(
            status_code=403, detail="Host identity assertion did not match request"
        )
    if lease.status != "active" or lease.expires_at <= datetime.utcnow():
        if lease.status == "active":
            crud.secret_keys.update_capability_lease(db, lease=lease, status="expired")
        raise HTTPException(status_code=409, detail="Capability lease is not active")
    if lease.single_use and lease.used_at is not None:
        raise HTTPException(
            status_code=409, detail="Capability lease has already been used"
        )
    if not compare_digest(
        lease.action_hash, _capability_action_hash(request.action, body.parameters)
    ):
        raise HTTPException(
            status_code=403, detail="Capability parameters did not match lease"
        )
    # Executor bindings are server-side.  The receipt executor is intentionally
    # side-effect-free for enrollment and policy rollout; real executors must be
    # installed behind the same binding rather than returning credentials.
    if capability.executor_kind != CAPABILITY_RECEIPT_EXECUTOR:
        raise HTTPException(
            status_code=501, detail="Capability executor is not installed"
        )
    receipt_uuid = str(uuid.uuid4())
    lease = crud.secret_keys.update_capability_lease(
        db,
        lease=lease,
        used_at=datetime.utcnow(),
        status="used" if lease.single_use else "active",
        invocation_receipt_uuid=receipt_uuid,
    )
    crud.secret_keys.create_capability_audit_event(
        db,
        request_id=request.id,
        lease_id=lease.id,
        event_type="capability_completed",
        actor_type=request.requester_type,
        actor_id=request.requester_id,
        summary=f"Completed capability {capability.name} action {request.action}",
        metadata_json={
            "host_id": enrollment.host_id,
            **_capability_summary_parameters(body.parameters),
        },
    )
    return {
        "receipt_id": receipt_uuid,
        "lease_id": lease.lease_uuid,
        "request_id": request.request_uuid,
        "capability": capability.name,
        "action": request.action,
        "host_id": enrollment.host_id,
        "status": "completed",
        "completed_at": datetime.utcnow(),
    }


def revoke_capability_lease(db: Session, *, lease_uuid: str, actor_id: int):
    lease = crud.secret_keys.get_capability_lease(db, lease_uuid=lease_uuid)
    if not lease:
        raise HTTPException(status_code=404, detail="Capability lease not found")
    if lease.status == "revoked":
        return lease
    lease = crud.secret_keys.update_capability_lease(
        db,
        lease=lease,
        status="revoked",
        revoked_by=actor_id,
        revoked_at=datetime.utcnow(),
    )
    crud.secret_keys.create_capability_audit_event(
        db,
        request_id=lease.request_id,
        lease_id=lease.id,
        event_type="capability_revoked",
        actor_type="operator",
        actor_id=str(actor_id),
        summary="Revoked capability lease",
        metadata_json={},
    )
    return lease
