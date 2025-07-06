"""API routes for :class:`~app.models.channel.Channel`."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud
from app.api.deps import get_db
from app.schemas import ChannelCreate, ChannelUpdate, Channel

router = APIRouter()

# Your endpoints and handlers go here


@router.post("/", response_model=Channel, status_code=status.HTTP_201_CREATED)
async def create_channel(channel: ChannelCreate, db: Session = Depends(get_db)):
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
        return crud.channel.create(db, obj_in=channel)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/", response_model=List[Channel])
async def get_channels(db: Session = Depends(get_db)):
    """Return all channels.

    Args:
        db: Database session dependency.

    Returns:
        List of channels.
    """
    return crud.channel.get_multi(db)


@router.get("/{channel_id}", response_model=Channel)
async def get_channel(channel_id: int, db: Session = Depends(get_db)):
    """Fetch a channel by ID.

    Args:
        channel_id: Identifier of the channel to fetch.
        db: Database session dependency.

    Returns:
        The requested channel.

    Raises:
        HTTPException: If the channel does not exist.
    """
    channel = crud.channel.get(db, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


@router.put("/{channel_id}", response_model=Channel)
async def update_channel(
    channel_id: int, channel: ChannelUpdate, db: Session = Depends(get_db)
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
    db_channel = crud.channel.get(db, channel_id)
    if not db_channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return crud.channel.update(db, db_obj=db_channel, obj_in=channel)


@router.delete("/{channel_id}", response_model=Channel)
async def delete_channel(channel_id: int, db: Session = Depends(get_db)):
    """Delete a channel.

    Args:
        channel_id: Identifier of the channel to delete.
        db: Database session dependency.

    Returns:
        The deleted channel instance.

    Raises:
        HTTPException: If the channel does not exist.
    """
    channel = crud.channel.remove(db, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel
