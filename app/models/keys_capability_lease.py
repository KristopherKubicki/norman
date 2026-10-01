from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String

from app.db.base import Base


class KeysCapabilityLease(Base):
    __tablename__ = "keys_capability_leases"

    id = Column(Integer, primary_key=True, index=True)
    lease_uuid = Column(String, nullable=False, unique=True, index=True)
    request_id = Column(
        Integer, ForeignKey("keys_capability_requests.id"), nullable=False, index=True
    )
    capability_id = Column(
        Integer, ForeignKey("keys_capabilities.id"), nullable=False, index=True
    )
    host_enrollment_id = Column(
        Integer, ForeignKey("keys_host_enrollments.id"), nullable=False, index=True
    )
    action_hash = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active", index=True)
    single_use = Column(Boolean, nullable=False, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True))
    invocation_receipt_uuid = Column(String, unique=True, index=True)
    revoked_at = Column(DateTime(timezone=True))
    revoked_by = Column(Integer, ForeignKey("users.id"), index=True)
