"""Capability authentication; raw-secret compatibility authentication is separate."""

import json
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.api.deps import get_db, _cached_or_db_user_for_service_token
from app.core.config import settings
from app.services.keys_host_auth import authenticate_host


async def get_keys_capability_user(request: Request, db: Session = Depends(get_db)):
    """Authenticate host signatures without accepting bearer-only host assertions."""
    body = await request.body()
    if len(body) > 16384:
        raise HTTPException(413, "Capability request too large")
    try:
        payload = json.loads(body)
        host_id = payload["host_id"]
        if not isinstance(host_id, str):
            raise ValueError("Invalid host")
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "Invalid capability request") from None
    request.state.keys_fingerprint = authenticate_host(
        db,
        host_id=host_id,
        path=request.url.path,
        body=body,
        public_key=request.headers.get("X-Norman-Host-Key", ""),
        signature=request.headers.get("X-Norman-Host-Signature", ""),
        timestamp=request.headers.get("X-Norman-Host-Time", ""),
        nonce=request.headers.get("X-Norman-Host-Nonce", ""),
    )
    email = (
        settings.norman_keys_service_user_email
        or settings.console_runtime_service_user_email
        or settings.initial_admin_email
        or ""
    ).strip()
    if not email:
        raise HTTPException(503, "Capability service identity is not configured")
    return _cached_or_db_user_for_service_token(
        db, email=email, missing_detail="Capability service identity was not found"
    )
