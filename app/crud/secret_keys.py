from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    SecretAlias,
    SecretAuditEvent,
    SecretLease,
    SecretPolicy,
    SecretProvider,
    SecretRequest,
    SecretStashItem,
)


def get_alias(db: Session, *, name: str) -> Optional[SecretAlias]:
    return (
        db.query(SecretAlias)
        .filter(SecretAlias.name == name, SecretAlias.enabled.is_(True))
        .first()
    )


def list_aliases(db: Session) -> list[SecretAlias]:
    return (
        db.query(SecretAlias)
        .filter(SecretAlias.enabled.is_(True))
        .order_by(SecretAlias.name.asc())
        .all()
    )


def get_provider(db: Session, *, provider_id: int) -> Optional[SecretProvider]:
    return (
        db.query(SecretProvider)
        .filter(SecretProvider.id == provider_id, SecretProvider.enabled.is_(True))
        .first()
    )


def list_policies(db: Session) -> list[SecretPolicy]:
    return (
        db.query(SecretPolicy)
        .filter(SecretPolicy.enabled.is_(True))
        .order_by(SecretPolicy.id.asc())
        .all()
    )


def create_request(
    db: Session,
    *,
    user_id: int,
    request_uuid: str,
    requester_type: str,
    requester_id: str,
    session_id: str,
    secret_alias: str,
    requested_mode: str,
    requested_ttl_seconds: int,
    lane: str,
    intent: str,
    reason: str,
    target_host: str,
    status: str,
    policy_id: Optional[int],
    approval_required: bool,
    approval_reason: str,
) -> SecretRequest:
    obj = SecretRequest(
        user_id=user_id,
        request_uuid=request_uuid,
        requester_type=requester_type,
        requester_id=requester_id,
        session_id=session_id or "",
        secret_alias=secret_alias,
        requested_mode=requested_mode,
        requested_ttl_seconds=requested_ttl_seconds,
        lane=lane or "",
        intent=intent or "",
        reason=reason or "",
        target_host=target_host or "",
        status=status,
        policy_id=policy_id,
        approval_required=approval_required,
        approval_reason=approval_reason or "",
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_request(db: Session, *, request_id: int) -> Optional[SecretRequest]:
    return db.query(SecretRequest).filter(SecretRequest.id == request_id).first()


def list_requests(
    db: Session, *, user_id: int, status: str = "", limit: int = 100
) -> list[SecretRequest]:
    q = db.query(SecretRequest).filter(SecretRequest.user_id == user_id)
    if status:
        q = q.filter(SecretRequest.status == status)
    return q.order_by(SecretRequest.id.desc()).limit(limit).all()


def decide_request(
    db: Session,
    *,
    request: SecretRequest,
    status: str,
    decided_by: int,
    approval_reason: str = "",
) -> SecretRequest:
    request.status = status
    request.decided_at = datetime.utcnow()
    request.decided_by = decided_by
    if approval_reason:
        request.approval_reason = approval_reason
    db.commit()
    db.refresh(request)
    return request


def create_lease(
    db: Session,
    *,
    lease_uuid: str,
    request_id: int,
    provider_id: int,
    provider_lease_id: str,
    secret_alias: str,
    granted_mode: str,
    granted_ttl_seconds: int,
    renewable: bool,
    status: str,
    issued_to: str,
    expires_at: datetime,
) -> SecretLease:
    obj = SecretLease(
        lease_uuid=lease_uuid,
        request_id=request_id,
        provider_id=provider_id,
        provider_lease_id=provider_lease_id or "",
        secret_alias=secret_alias,
        granted_mode=granted_mode,
        granted_ttl_seconds=granted_ttl_seconds,
        renewable=renewable,
        status=status,
        issued_to=issued_to,
        expires_at=expires_at,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_lease(db: Session, *, lease_id: int) -> Optional[SecretLease]:
    return db.query(SecretLease).filter(SecretLease.id == lease_id).first()


def list_active_leases(db: Session, *, user_id: int) -> list[SecretLease]:
    return (
        db.query(SecretLease)
        .join(SecretRequest, SecretRequest.id == SecretLease.request_id)
        .filter(SecretRequest.user_id == user_id, SecretLease.status == "active")
        .order_by(SecretLease.expires_at.asc())
        .all()
    )


def update_lease(
    db: Session,
    *,
    lease: SecretLease,
    expires_at: Optional[datetime] = None,
    status: Optional[str] = None,
    revoked_by: Optional[int] = None,
) -> SecretLease:
    if expires_at is not None:
        lease.expires_at = expires_at
    if status:
        lease.status = status
    if revoked_by is not None:
        lease.revoked_by = revoked_by
        lease.revoked_at = datetime.utcnow()
    lease.last_used_at = datetime.utcnow()
    db.commit()
    db.refresh(lease)
    return lease


def create_audit_event(
    db: Session,
    *,
    user_id: Optional[int] = None,
    request_id: Optional[int],
    lease_id: Optional[int],
    event_type: str,
    actor_type: str,
    actor_id: str,
    summary: str,
    metadata_json: Optional[dict] = None,
) -> SecretAuditEvent:
    obj = SecretAuditEvent(
        user_id=user_id,
        request_id=request_id,
        lease_id=lease_id,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        summary=summary,
        metadata_json=metadata_json or {},
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def list_audit_events(
    db: Session, *, user_id: int, limit: int = 100
) -> list[SecretAuditEvent]:
    return (
        db.query(SecretAuditEvent)
        .outerjoin(SecretRequest, SecretRequest.id == SecretAuditEvent.request_id)
        .filter(
            (SecretRequest.user_id == user_id) | (SecretAuditEvent.user_id == user_id)
        )
        .order_by(SecretAuditEvent.id.desc())
        .limit(limit)
        .all()
    )


def create_stash_item(
    db: Session,
    *,
    pointer_token: str,
    user_id: int,
    channel_id: Optional[int],
    label: str,
    encrypted_value: str,
    masked_preview: str,
    source: str,
    expires_at: datetime,
) -> SecretStashItem:
    obj = SecretStashItem(
        pointer_token=pointer_token,
        user_id=user_id,
        channel_id=channel_id,
        label=label,
        encrypted_value=encrypted_value,
        masked_preview=masked_preview,
        source=source,
        status="active",
        expires_at=expires_at,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_stash_item(db: Session, *, pointer_token: str) -> Optional[SecretStashItem]:
    return (
        db.query(SecretStashItem)
        .filter(SecretStashItem.pointer_token == pointer_token)
        .first()
    )


def list_active_stash_items(
    db: Session, *, user_id: int, limit: int = 100
) -> list[SecretStashItem]:
    return (
        db.query(SecretStashItem)
        .filter(
            SecretStashItem.user_id == user_id,
            SecretStashItem.status == "active",
            SecretStashItem.expires_at > datetime.utcnow(),
        )
        .order_by(SecretStashItem.expires_at.asc())
        .limit(limit)
        .all()
    )


def update_stash_item(
    db: Session,
    *,
    item: SecretStashItem,
    status: Optional[str] = None,
    last_used_at: Optional[datetime] = None,
    revoked_by: Optional[int] = None,
) -> SecretStashItem:
    if status:
        item.status = status
    if last_used_at is not None:
        item.last_used_at = last_used_at
    if revoked_by is not None:
        item.revoked_by = revoked_by
        item.revoked_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return item
