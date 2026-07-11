from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_keys_service_user
from app import crud
from app.schemas.secret_keys import (
    SecretAliasOut,
    SecretCompatGetRequest,
    SecretCompatGetResponse,
    SecretLeaseOut,
    SecretLeaseRenew,
    SecretRequestCreate,
    SecretRequestDecision,
    SecretRequestOut,
    SecretRequestResult,
    SecretAuditEventOut,
    SecretStashCreate,
    SecretStashOut,
)
from app.services.secret_keys import (
    approve_secret_request,
    create_secret_request,
    create_secret_stash_item,
    reject_secret_request,
    renew_secret_lease,
    revoke_secret_stash_item,
    revoke_secret_lease,
    serialize_secret_stash_item,
)

router = APIRouter(prefix="/keys", tags=["keys"])
compat_router = APIRouter(tags=["keys_compat"])


@router.get("/aliases", response_model=list[SecretAliasOut])
def list_aliases(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return crud.secret_keys.list_aliases(db)


@router.get("/requests", response_model=list[SecretRequestOut])
def list_requests(
    status: str = Query("", description="Filter by status"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return crud.secret_keys.list_requests(
        db, user_id=current_user.id, status=status, limit=limit
    )


@router.post("/requests", response_model=SecretRequestResult)
def request_secret(
    body: SecretRequestCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    request, lease, secret_value, provider_kind, warnings = create_secret_request(
        db, user_id=current_user.id, body=body
    )
    payload = {
        "request": request,
        "lease": lease,
        "provider": provider_kind,
        "delivery_mode": body.requested_mode,
        "warnings": warnings,
    }
    if body.requested_mode == "read" and secret_value is not None:
        payload["secret"] = secret_value
        payload["value"] = secret_value
    return SecretRequestResult(**payload)


@router.post("/requests/{request_id}/approve", response_model=SecretRequestResult)
def approve_request(
    request_id: int,
    body: SecretRequestDecision,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    request, lease, secret_value, provider_kind = approve_secret_request(
        db,
        request_id=request_id,
        decided_by=current_user.id,
        reason=body.reason,
        ttl_override_seconds=body.ttl_seconds,
    )
    payload = {
        "request": request,
        "lease": lease,
        "provider": provider_kind,
        "delivery_mode": request.requested_mode,
        "warnings": [],
    }
    if request.requested_mode == "read" and secret_value is not None:
        payload["secret"] = secret_value
        payload["value"] = secret_value
    return SecretRequestResult(**payload)


@router.post("/requests/{request_id}/reject", response_model=SecretRequestOut)
def reject_request(
    request_id: int,
    body: SecretRequestDecision,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return reject_secret_request(
        db, request_id=request_id, decided_by=current_user.id, reason=body.reason
    )


@router.get("/leases/active", response_model=list[SecretLeaseOut])
def list_active_leases(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return crud.secret_keys.list_active_leases(db, user_id=current_user.id)


@router.post("/leases/{lease_id}/renew", response_model=SecretLeaseOut)
def renew_lease(
    lease_id: int,
    body: SecretLeaseRenew,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return renew_secret_lease(
        db, lease_id=lease_id, ttl_seconds=body.ttl_seconds, actor_id=current_user.id
    )


@router.post("/leases/{lease_id}/revoke", response_model=SecretLeaseOut)
def revoke_lease(
    lease_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return revoke_secret_lease(db, lease_id=lease_id, actor_id=current_user.id)


@router.get("/audit", response_model=list[SecretAuditEventOut])
def list_audit(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return crud.secret_keys.list_audit_events(db, user_id=current_user.id, limit=limit)


@router.get("/stash", response_model=list[SecretStashOut])
def list_secret_stash(
    channel_id: int | None = Query(default=None, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if channel_id is not None:
        channel = crud.channel.get_for_user(db, channel_id, current_user.id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
    items = crud.secret_keys.list_stash_items(
        db,
        user_id=current_user.id,
        channel_id=channel_id,
        active_only=True,
        limit=limit,
    )
    return [serialize_secret_stash_item(item) for item in items]


@router.post("/stash", response_model=SecretStashOut, status_code=201)
def create_secret_stash(
    body: SecretStashCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if body.channel_id is not None:
        channel = crud.channel.get_for_user(db, body.channel_id, current_user.id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
    item = create_secret_stash_item(db, user_id=current_user.id, body=body)
    return serialize_secret_stash_item(item)


@router.post("/stash/{stash_id}/revoke", response_model=SecretStashOut)
def revoke_secret_stash(
    stash_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    item = revoke_secret_stash_item(
        db,
        stash_id=stash_id,
        user_id=current_user.id,
        revoked_by=current_user.id,
    )
    return serialize_secret_stash_item(item)


@compat_router.post("/v1/secrets/get", response_model=SecretCompatGetResponse)
def get_secret_compat(
    body: SecretCompatGetRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_keys_service_user),
):
    """Compatibility broker endpoint for clients using Norman Keys as a resolver."""

    request_body = SecretRequestCreate(
        name=body.name,
        requested_mode="read",
        requested_ttl_seconds=body.ttl_seconds,
        requester_type=body.requester_type,
        requester_id=body.requester_id or "runtime-tui-bridge",
        session_id=body.session_id,
        lane=body.lane,
        intent=body.intent,
        reason=body.reason or "compat secret get",
        target_host=body.target_host,
    )
    request, lease, secret_value, provider_kind, warnings = create_secret_request(
        db, user_id=current_user.id, body=request_body
    )
    if lease is None or secret_value is None:
        raise HTTPException(
            status_code=409, detail="Secret request requires approval before reveal"
        )
    return SecretCompatGetResponse(
        secret=secret_value,
        value=secret_value,
        lease_id=lease.lease_uuid,
        request_id=request.request_uuid,
        expires_at=lease.expires_at,
        provider=provider_kind,
        warnings=warnings,
    )
