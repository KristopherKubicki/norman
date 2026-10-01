from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String
from sqlalchemy.sql import func

from app.db.base import Base


class KeysHostEnrollment(Base):
    """An enrolled Norman Keys client host.

    ``identity_fingerprint`` is a public certificate/key fingerprint supplied by
    the trusted mTLS gateway.  It is deliberately not a host secret.
    """

    __tablename__ = "keys_host_enrollments"

    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(String, nullable=False, unique=True, index=True)
    hostname = Column(String, nullable=False, unique=True, index=True)
    identity_fingerprint = Column(String, nullable=False)
    requester_ids = Column(JSON, nullable=False, default=list)
    capability_names = Column(JSON, nullable=False, default=list)
    lanes = Column(JSON, nullable=False, default=list)
    status = Column(String, nullable=False, default="active", index=True)
    notes = Column(String, nullable=False, default="")
    last_seen_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
