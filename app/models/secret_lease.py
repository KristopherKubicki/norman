from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String

from app.db.base import Base


class SecretLease(Base):
    __tablename__ = "secret_leases"

    id = Column(Integer, primary_key=True, index=True)
    lease_uuid = Column(String, nullable=False, unique=True, index=True)
    request_id = Column(
        Integer, ForeignKey("secret_requests.id"), nullable=False, index=True
    )
    provider_id = Column(
        Integer, ForeignKey("secret_providers.id"), nullable=False, index=True
    )
    provider_lease_id = Column(String, index=True)
    secret_alias = Column(String, nullable=False, index=True)
    granted_mode = Column(String, nullable=False, default="inject")
    granted_ttl_seconds = Column(Integer, nullable=False, default=900)
    renewable = Column(Boolean, nullable=False, default=True)
    status = Column(String, nullable=False, default="active", index=True)
    issued_to = Column(String, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    last_used_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    revoked_by = Column(Integer, ForeignKey("users.id"), index=True)
