from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
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
    KeysCapabilityAuditEventOut,
    KeysCapabilityCreate,
    KeysCapabilityDecision,
    KeysCapabilityInvoke,
    KeysCapabilityPolicyCreate,
    KeysCapabilityPolicyOut,
    KeysCapabilityRequestCreate,
    KeysCapabilityRequestResult,
    KeysCapabilityReceipt,
    KeysCapabilityRequestOut,
    KeysCapabilityOut,
    KeysHostEnrollmentCreate,
    KeysHostEnrollmentOut,
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
    approve_capability_request,
    create_capability_request,
    invoke_capability_lease,
    reject_capability_request,
    revoke_capability_lease,
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


@router.get("/enrollments", response_model=list[KeysHostEnrollmentOut])
def list_keys_host_enrollments(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return crud.secret_keys.list_host_enrollments(db)


@router.post("/enrollments", response_model=KeysHostEnrollmentOut, status_code=201)
def enroll_keys_host(
    body: KeysHostEnrollmentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if crud.secret_keys.get_host_enrollment(db, host_id=body.host_id):
        raise HTTPException(status_code=409, detail="Host is already enrolled")
    return crud.secret_keys.create_host_enrollment(
        db,
        host_id=body.host_id,
        hostname=body.hostname,
        identity_fingerprint=body.identity_fingerprint,
        requester_ids=body.requester_ids,
        capability_names=body.capability_names,
        lanes=body.lanes,
        status="active",
        notes=body.notes,
    )


@router.get("/capabilities", response_model=list[KeysCapabilityOut])
def list_keys_capabilities(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return crud.secret_keys.list_capabilities(db)


@router.post("/capabilities", response_model=KeysCapabilityOut, status_code=201)
def create_keys_capability(
    body: KeysCapabilityCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if crud.secret_keys.get_capability(db, name=body.name, active_only=False):
        raise HTTPException(status_code=409, detail="Capability already exists")
    return crud.secret_keys.create_capability(db, **body.dict())


@router.get("/capability-policies", response_model=list[KeysCapabilityPolicyOut])
def list_keys_capability_policies(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return crud.secret_keys.list_capability_policies(db)


@router.post(
    "/capability-policies", response_model=KeysCapabilityPolicyOut, status_code=201
)
def create_keys_capability_policy(
    body: KeysCapabilityPolicyCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    capability = crud.secret_keys.get_capability(
        db, name=body.capability_name, active_only=False
    )
    if not capability:
        raise HTTPException(status_code=404, detail="Capability not found")
    if crud.secret_keys.get_capability_policy(db, name=body.name):
        raise HTTPException(status_code=409, detail="Capability policy already exists")
    values = body.dict(exclude={"capability_name"})
    return crud.secret_keys.create_capability_policy(
        db, capability_id=capability.id, **values
    )


@router.get("/capability-audit", response_model=list[KeysCapabilityAuditEventOut])
def list_keys_capability_audit(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return crud.secret_keys.list_capability_audit_events(db, limit=limit)


@router.post(
    "/capability-requests/{request_id}/approve",
    response_model=KeysCapabilityRequestResult,
)
def approve_keys_capability_request(
    request_id: int,
    body: KeysCapabilityDecision,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    request, lease, capability, enrollment = approve_capability_request(
        db,
        request_id=request_id,
        decided_by=current_user.id,
        reason=body.reason,
        ttl_seconds=body.ttl_seconds,
    )
    return KeysCapabilityRequestResult(
        request=request,
        lease={
            "lease_id": lease.lease_uuid,
            "request_id": request.request_uuid,
            "capability": capability.name,
            "host_id": enrollment.host_id,
            "action": request.action,
            "expires_at": lease.expires_at,
            "single_use": lease.single_use,
            "status": lease.status,
        },
    )


@router.post(
    "/capability-requests/{request_id}/reject", response_model=KeysCapabilityRequestOut
)
def reject_keys_capability_request(
    request_id: int,
    body: KeysCapabilityDecision,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return reject_capability_request(
        db, request_id=request_id, decided_by=current_user.id, reason=body.reason
    )


@router.post("/capability-leases/{lease_id}/revoke")
def revoke_keys_capability_lease(
    lease_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    lease = revoke_capability_lease(db, lease_uuid=lease_id, actor_id=current_user.id)
    return {"lease_id": lease.lease_uuid, "status": lease.status}


@compat_router.post(
    "/v1/capabilities/request", response_model=KeysCapabilityRequestResult
)
def request_capability_compat(
    body: KeysCapabilityRequestCreate,
    x_norman_keys_host_fingerprint: str = Header(default=""),
    db: Session = Depends(get_db),
    current_user=Depends(get_keys_service_user),
):
    request, lease, capability, enrollment = create_capability_request(
        db,
        user_id=current_user.id,
        body=body,
        asserted_fingerprint=x_norman_keys_host_fingerprint,
    )
    payload = {"request": request, "warnings": []}
    if lease:
        payload["lease"] = {
            "lease_id": lease.lease_uuid,
            "request_id": request.request_uuid,
            "capability": capability.name,
            "host_id": enrollment.host_id,
            "action": request.action,
            "expires_at": lease.expires_at,
            "single_use": lease.single_use,
            "status": lease.status,
        }
    return KeysCapabilityRequestResult(**payload)


@compat_router.post(
    "/v1/capabilities/{lease_id}/invoke", response_model=KeysCapabilityReceipt
)
def invoke_capability_compat(
    lease_id: str,
    body: KeysCapabilityInvoke,
    x_norman_keys_host_fingerprint: str = Header(default=""),
    db: Session = Depends(get_db),
    current_user=Depends(get_keys_service_user),
):
    return invoke_capability_lease(
        db,
        lease_uuid=lease_id,
        body=body,
        asserted_fingerprint=x_norman_keys_host_fingerprint,
    )
