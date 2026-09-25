"""Durable replay prevention across broker workers and restarts."""

from sqlalchemy import BigInteger, Column, String
from app.db.base import Base


class KeysTransportNonce(Base):
    __tablename__ = "keys_transport_nonces"

    digest = Column(String(64), primary_key=True)
    expires_at = Column(BigInteger, nullable=False, index=True)
