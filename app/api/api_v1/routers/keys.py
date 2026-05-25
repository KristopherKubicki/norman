from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app import crud
from app.schemas.secret_keys import (
    SecretAliasOut,
    SecretLeaseOut,
    SecretLeaseRenew,
    SecretRequestCreate,
    SecretRequestDecision,
    SecretRequestOut,
    SecretRequestResult,
    SecretStashCreate,
    SecretStashOut,
    SecretAuditEventOut,
)
from app.services.secret_keys import (
    approve_secret_request,
    create_secret_request,
    create_secret_stash_item,
    list_secret_stash_items,
    reject_secret_request,
    revoke_secret_stash_item,
    renew_secret_lease,
    revoke_secret_lease,
)

router = APIRouter(prefix="/keys", tags=["keys"])


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


@router.post("/stash", response_model=SecretStashOut)
def stash_secret(
    body: SecretStashCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return create_secret_stash_item(db, user_id=current_user.id, body=body)


@router.get("/stash", response_model=list[SecretStashOut])
def list_stash(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return list_secret_stash_items(db, user_id=current_user.id, limit=limit)


@router.post("/stash/{pointer_token}/revoke", response_model=SecretStashOut)
def revoke_stash(
    pointer_token: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return revoke_secret_stash_item(
        db, pointer_token=pointer_token, user_id=current_user.id
    )


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
