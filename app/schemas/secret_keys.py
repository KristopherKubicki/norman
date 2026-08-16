from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import ConfigDict, BaseModel, Field
PYDANTIC_V2 = hasattr(BaseModel, "model_validate")
NONEMPTY_LIST_FIELD = (
    Field(..., min_length=1) if PYDANTIC_V2 else Field(..., min_items=1)
)


class SecretAliasOut(BaseModel):
    id: int
    name: str
    lane: str
    default_ttl_seconds: int
    allow_raw_reveal: bool
    provider_id: int

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


class SecretRequestResult(BaseModel):
    request: SecretRequestOut
    lease: Optional[SecretLeaseOut] = None
    secret: Optional[str] = None
    value: Optional[str] = None
    delivery_mode: str = "inject"
    provider: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class SecretCompatGetRequest(BaseModel):
    name: str
    ttl_seconds: int = Field(900, ge=60, le=86400)
    requester_type: str = "agent"
    requester_id: str = "runtime-tui-bridge"
    session_id: str = ""
    lane: str = ""
    intent: str = "compat-secret-get"
    reason: str = "compat secret get"
    target_host: str = ""


class SecretCompatGetResponse(BaseModel):
    secret: str
    value: str
    lease_id: str = ""
    request_id: str = ""
    expires_at: Optional[datetime] = None
    provider: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class SecretAuditEventOut(BaseModel):
    id: int
    request_id: Optional[int] = None
    lease_id: Optional[int] = None
    event_type: str
    actor_type: str
    actor_id: Optional[str] = None
    summary: str
    metadata_json: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SecretStashCreate(BaseModel):
    channel_id: Optional[int] = None
    label: str = Field(default="", max_length=120)
    value: str = Field(..., min_length=1, max_length=65535)
    ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    source: str = Field(default="manual", max_length=32)


class SecretStashOut(BaseModel):
    id: int
    channel_id: Optional[int] = None
    label: str
    masked_preview: str
    source: str
    status: str
    pointer: str
    prompt_reference: str
    created_at: Optional[datetime] = None
    expires_at: datetime
    revoked_at: Optional[datetime] = None


class KeysOrmResponseModel(BaseModel):
    if PYDANTIC_V2:
        model_config = ConfigDict(from_attributes=True)
    else:

        class Config:
            orm_mode = True


class KeysHostEnrollmentCreate(BaseModel):
    host_id: str = Field(..., min_length=1, max_length=120)
    hostname: str = Field(..., min_length=1, max_length=255)
    identity_fingerprint: str = Field(..., min_length=16, max_length=512)
    requester_ids: list[str] = Field(default_factory=list)
    capability_names: list[str] = Field(default_factory=list)
    lanes: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=500)


class KeysHostEnrollmentOut(KeysOrmResponseModel):
    id: int
    host_id: str
    hostname: str
    identity_fingerprint: str
    requester_ids: list[str] = Field(default_factory=list)
    capability_names: list[str] = Field(default_factory=list)
    lanes: list[str] = Field(default_factory=list)
    status: str
    notes: str = ""
    last_seen_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

class KeysCapabilityCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    executor_kind: str = Field(default="receipt", min_length=1, max_length=64)
    executor_ref: str = Field(default="", max_length=512)
    secret_aliases: list[str] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False


class KeysCapabilityOut(KeysOrmResponseModel):
    id: int
    name: str
    executor_kind: str
    executor_ref: str
    secret_aliases: list[str] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    enabled: bool

class KeysCapabilityPolicyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    capability_name: str = Field(..., min_length=1, max_length=160)
    requester_type: str = Field(default="agent", min_length=1, max_length=64)
    requester_id: str = Field(default="", max_length=160)
    lane: str = Field(default="", max_length=120)
    allowed_actions: list[str] = NONEMPTY_LIST_FIELD
    allowed_target_hosts: list[str] = Field(default_factory=list)
    max_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    approval_required: bool = True
    enabled: bool = False


class KeysCapabilityPolicyOut(KeysOrmResponseModel):
    id: int
    name: str
    capability_id: int
    requester_type: str
    requester_id: Optional[str] = None
    lane: Optional[str] = None
    allowed_actions: list[str] = Field(default_factory=list)
    allowed_target_hosts: list[str] = Field(default_factory=list)
    max_ttl_seconds: int
    approval_required: bool
    enabled: bool

class KeysCapabilityRequestCreate(BaseModel):
    capability: str = Field(..., min_length=1, max_length=160)
    host_id: str = Field(..., min_length=1, max_length=120)
    identity_fingerprint: str = Field(..., min_length=16, max_length=512)
    requester_type: str = Field(default="agent", min_length=1, max_length=64)
    requester_id: str = Field(..., min_length=1, max_length=160)
    session_id: str = Field(default="", max_length=255)
    lane: str = Field(default="", max_length=120)
    action: str = Field(..., min_length=1, max_length=120)
    parameters: dict[str, Any] = Field(default_factory=dict)
    target_host: str = Field(default="", max_length=255)
    reason: str = Field(default="", max_length=1000)
    requested_ttl_seconds: int = Field(default=900, ge=60, le=86400)


class KeysCapabilityRequestOut(KeysOrmResponseModel):
    id: int
    request_uuid: str
    host_enrollment_id: int
    capability_id: int
    policy_id: int
    requester_type: str
    requester_id: str
    session_id: str
    lane: str
    action: str
    action_hash: str
    target_host: str
    reason: str
    requested_ttl_seconds: int
    status: str
    approval_required: bool
    approval_reason: str
    created_at: Optional[datetime] = None

class KeysCapabilityLeaseOut(BaseModel):
    lease_id: str
    request_id: str
    capability: str
    host_id: str
    action: str
    expires_at: datetime
    single_use: bool
    status: str


class KeysCapabilityRequestResult(BaseModel):
    request: KeysCapabilityRequestOut
    lease: Optional[KeysCapabilityLeaseOut] = None
    warnings: list[str] = Field(default_factory=list)


class KeysCapabilityInvoke(BaseModel):
    host_id: str = Field(..., min_length=1, max_length=120)
    identity_fingerprint: str = Field(..., min_length=16, max_length=512)
    parameters: dict[str, Any] = Field(default_factory=dict)


class KeysCapabilityReceipt(BaseModel):
    receipt_id: str
    lease_id: str
    request_id: str
    capability: str
    action: str
    host_id: str
    status: str
    completed_at: datetime


class KeysCapabilityAuditEventOut(KeysOrmResponseModel):
    id: int
    request_id: Optional[int] = None
    lease_id: Optional[int] = None
    event_type: str
    actor_type: str
    actor_id: str
    summary: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None

class KeysCapabilityDecision(BaseModel):
    reason: str = Field(default="", max_length=1000)
    ttl_seconds: Optional[int] = Field(default=None, ge=60, le=86400)
