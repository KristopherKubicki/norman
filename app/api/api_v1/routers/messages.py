from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import Message as MessageModel
from app.schemas.message import Message

router = APIRouter()

@router.get("/", response_model=List[Message])
async def get_messages(
    db: Session = Depends(get_db),
    connector_id: Optional[int] = None,
    channel_id: Optional[int] = None,
    bot_id: Optional[int] = None,
    q: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
):
    """Return messages filtered by the provided criteria."""
    try:
        query = db.query(MessageModel)
        if bot_id is not None:
            query = query.filter(MessageModel.bot_id == bot_id)
        # connector_id and channel_id are accepted but currently unused
        if start is not None:
            query = query.filter(MessageModel.created_at >= start)
        if end is not None:
            query = query.filter(MessageModel.created_at <= end)
        if q:
            query = query.filter(MessageModel.text.ilike(f"%{q}%"))
        query = query.order_by(MessageModel.created_at)
        messages = query.all()
        return [Message.from_orm(m) for m in messages]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
