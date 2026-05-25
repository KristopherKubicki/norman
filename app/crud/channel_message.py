from typing import List

from sqlalchemy.orm import Session

from app.models.channel_message import ChannelMessage
from app.schemas.channel_message import ChannelMessageCreate


def create(
    db: Session,
    channel_id: int,
    message_in: ChannelMessageCreate,
    source: str = "user",
) -> ChannelMessage:
    db_obj = ChannelMessage(
        channel_id=channel_id,
        content=message_in.content,
        source=(source or "user").strip() or "user",
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def get_by_channel(
    db: Session, channel_id: int, limit: int = 100
) -> List[ChannelMessage]:
    return (
        db.query(ChannelMessage)
        .filter(ChannelMessage.channel_id == channel_id)
        .order_by(ChannelMessage.created_at.asc())
        .limit(limit)
        .all()
    )


def delete_by_channel(db: Session, channel_id: int) -> int:
    deleted = (
        db.query(ChannelMessage)
        .filter(ChannelMessage.channel_id == channel_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted
