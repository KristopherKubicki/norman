from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.command_approval import CommandApproval


def create(
    db: Session,
    *,
    user_id: int,
    connector_id: int,
    event_id: Optional[int],
    command_text: str,
    command_class: str,
    reason: str,
    confirm_token: str = "",
) -> CommandApproval:
    obj = CommandApproval(
        user_id=user_id,
        connector_id=connector_id,
        event_id=event_id,
        command_text=command_text,
        command_class=command_class,
        status="pending",
        reason=reason,
        confirm_token=confirm_token or "",
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get(db: Session, approval_id: int) -> Optional[CommandApproval]:
    return db.query(CommandApproval).filter(CommandApproval.id == approval_id).first()


def count_by_user(db: Session, *, user_id: int, status: str = "") -> int:
    q = db.query(CommandApproval).filter(CommandApproval.user_id == user_id)
    if status:
        q = q.filter(CommandApproval.status == status)
    return int(q.count())


def list_by_user(
    db: Session, *, user_id: int, status: str = "", limit: int = 200
) -> List[CommandApproval]:
    q = db.query(CommandApproval).filter(CommandApproval.user_id == user_id)
    if status:
        q = q.filter(CommandApproval.status == status)
    return q.order_by(CommandApproval.id.desc()).limit(limit).all()


def decide(
    db: Session,
    *,
    approval: CommandApproval,
    status: str,
    reason: str = "",
) -> CommandApproval:
    approval.status = status
    approval.decided_at = datetime.utcnow()
    if reason:
        approval.reason = reason
    db.commit()
    db.refresh(approval)
    return approval
