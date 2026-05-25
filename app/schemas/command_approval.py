from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class CommandApprovalOut(BaseModel):
    id: int
    user_id: int
    connector_id: int
    event_id: Optional[int] = None

    command_text: str
    command_class: str
    status: str
    reason: Optional[str] = None
    confirm_token: Optional[str] = None
    created_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class CommandApprovalDecision(BaseModel):
    confirm_token: Optional[str] = None
    reason: Optional[str] = None
