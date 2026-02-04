"""API routes for :class:`~app.models.channel.Channel`."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crud
from app.crud.channel_message import create as create_channel_message_record
from app.crud.channel_message import get_by_channel as get_channel_message_records
from app.api.deps import get_db, get_current_user
from app.models import User
from app.schemas import (
    ChannelCreate,
    ChannelUpdate,
    Channel,
    ChannelMessageCreate,
    ChannelMessageOut,
)

router = APIRouter()

# Your endpoints and handlers go here


@router.post("", response_model=Channel, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=Channel, status_code=status.HTTP_201_CREATED)
async def create_channel(
    channel: ChannelCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new channel.

    Args:
        channel: Channel data to persist.
        db: Database session dependency.

    Returns:
        The created channel instance.

    Raises:
        HTTPException: If the channel could not be created.
    """
    try:
        connector = crud.connector.get(db, channel.connector_id)
        if not connector or connector.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Connector not found")
        return crud.channel.create(db, obj_in=channel)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=List[Channel])
@router.get("/", response_model=List[Channel])
async def get_channels(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all channels.

    Args:
        db: Database session dependency.

    Returns:
        List of channels.
    """
    return crud.channel.get_multi_by_user(db, current_user.id)


@router.get("/{channel_id}", response_model=Channel)
async def get_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch a channel by ID.

    Args:
        channel_id: Identifier of the channel to fetch.
        db: Database session dependency.

    Returns:
        The requested channel.

    Raises:
        HTTPException: If the channel does not exist.
    """
    channel = crud.channel.get_for_user(db, channel_id, current_user.id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


@router.put("/{channel_id}", response_model=Channel)
async def update_channel(
    channel_id: int,
    channel: ChannelUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a channel.

    Args:
        channel_id: Identifier of the channel to update.
        channel: New channel values.
        db: Database session dependency.

    Returns:
        The updated channel instance.

    Raises:
        HTTPException: If the channel does not exist.
    """
    db_channel = crud.channel.get_for_user(db, channel_id, current_user.id)
    if not db_channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if channel.connector_id is not None:
        connector = crud.connector.get(db, channel.connector_id)
        if not connector or connector.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Connector not found")
    return crud.channel.update(db, db_obj=db_channel, obj_in=channel)


@router.delete("/{channel_id}", response_model=Channel)
async def delete_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a channel.

    Args:
        channel_id: Identifier of the channel to delete.
        db: Database session dependency.

    Returns:
        The deleted channel instance.

    Raises:
        HTTPException: If the channel does not exist.
    """
    channel = crud.channel.get_for_user(db, channel_id, current_user.id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    try:
        return crud.channel.remove(db, channel_id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Channel has related records. Remove filters/messages first.",
        )


@router.get("/{channel_id}/messages", response_model=List[ChannelMessageOut])
async def get_channel_messages(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = crud.channel.get_for_user(db, channel_id, current_user.id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return get_channel_message_records(db, channel_id)


@router.post("/{channel_id}/messages", response_model=ChannelMessageOut)
async def create_channel_message(
    channel_id: int,
    payload: ChannelMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = crud.channel.get_for_user(db, channel_id, current_user.id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return create_channel_message_record(db, channel_id, payload)
