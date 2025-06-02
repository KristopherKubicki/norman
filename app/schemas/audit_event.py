from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class AuditEventBase(BaseModel):
    user_id: int
    event_type: str
    ip_address: Optional[str] = None


class AuditEventCreate(AuditEventBase):
    pass


class AuditEvent(AuditEventBase):
    id: int
    created_at: datetime

    class Config:
        orm_mode = True
