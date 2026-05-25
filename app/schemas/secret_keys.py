from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, validator


SECRET_REQUEST_MODES = {"inject", "env", "file", "read"}


class SecretAliasOut(BaseModel):
    id: int
    name: str
    lane: str
    default_ttl_seconds: int
    allow_raw_reveal: bool
    provider_id: int

    class Config:
        orm_mode = True


class SecretRequestCreate(BaseModel):
    name: str
    requested_mode: str = "inject"
    requested_ttl_seconds: int = Field(900, ge=60, le=86400)
    requester_type: str = "agent"
    requester_id: str = "norman-prime"
    session_id: str = ""
    lane: str = ""
    intent: str = ""
    reason: str = ""
    target_host: str = ""

    @validator("requested_mode")
    def validate_requested_mode(cls, value: str) -> str:
        mode = (value or "").strip().lower()
        if mode not in SECRET_REQUEST_MODES:
            allowed = ", ".join(sorted(SECRET_REQUEST_MODES))
            raise ValueError(f"requested_mode must be one of: {allowed}")
        return mode


class SecretRequestDecision(BaseModel):
    reason: str = ""
    ttl_seconds: Optional[int] = Field(default=None, ge=60, le=86400)


class SecretLeaseRenew(BaseModel):
    ttl_seconds: int = Field(900, ge=60, le=86400)


class SecretLeaseOut(BaseModel):
    id: int
    lease_uuid: str
    request_id: int
    provider_id: int
    provider_lease_id: Optional[str] = None
    secret_alias: str
    granted_mode: str
    granted_ttl_seconds: int
    renewable: bool
    status: str
    issued_to: str
    expires_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[int] = None

    class Config:
        orm_mode = True


class SecretRequestOut(BaseModel):
    id: int
    request_uuid: str
    user_id: int
    requester_type: str
    requester_id: str
    session_id: Optional[str] = None
    secret_alias: str
    requested_mode: str
    requested_ttl_seconds: int
    lane: Optional[str] = None
    intent: Optional[str] = None
    reason: Optional[str] = None
    target_host: Optional[str] = None
    status: str
    policy_id: Optional[int] = None
    approval_required: bool
    approval_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    decided_by: Optional[int] = None

    class Config:
        orm_mode = True


class SecretRequestResult(BaseModel):
    request: SecretRequestOut
    lease: Optional[SecretLeaseOut] = None
    secret: Optional[str] = None
    value: Optional[str] = None
    delivery_mode: str = "inject"
    provider: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class SecretStashCreate(BaseModel):
    value: str = Field(..., min_length=1)
    label: str = Field("secret", min_length=1, max_length=120)
    channel_id: Optional[int] = None
    ttl_seconds: int = Field(900, ge=60, le=86400)
    source: str = Field("manual", min_length=1, max_length=40)

    @validator("label", "source")
    def strip_text(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class SecretStashOut(BaseModel):
    id: int
    pointer_token: str
    pointer_uri: str
    user_id: int
    channel_id: Optional[int] = None
    label: str
    masked_preview: str
    source: str
    status: str
    created_at: Optional[datetime] = None
    expires_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[int] = None

    class Config:
        orm_mode = True


class SecretAuditEventOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    request_id: Optional[int] = None
    lease_id: Optional[int] = None
    event_type: str
    actor_type: str
    actor_id: Optional[str] = None
    summary: str
    metadata_json: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None

    class Config:
        orm_mode = True
