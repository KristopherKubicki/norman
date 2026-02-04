from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud, models
from app.schemas import FilterCreate, FilterUpdate, Filter
from app.api.deps import get_db, get_current_user
from app.models import User

router = APIRouter()


@router.post("/filters/", response_model=Filter, status_code=status.HTTP_201_CREATED)
async def create_channel_filter(
    channel_filter: FilterCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Filter:
    """Create a new channel filter.

    Args:
        channel_filter: Filter definition from the request.
        db: Database session dependency.

    Returns:
        The created filter instance.
    """
    channel = crud.channel.get_for_user(db, channel_filter.channel_id, current_user.id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return crud.channel_filter.create(db, obj_in=channel_filter)


@router.get("/filters/", response_model=List[Filter])
async def get_filters(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[Filter]:
    """Return all channel filters.

    Args:
        db: Database session dependency.

    Returns:
        List of channel filters.
    """
    return crud.channel_filter.get_multi_by_user(db, current_user.id)


@router.get("/filters/{channel_filter_id}", response_model=Filter)
async def get_channel_filter(
    channel_filter_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Filter:
    """Fetch a channel filter by ID.

    Args:
        channel_filter_id: Identifier of the filter.
        db: Database session dependency.

    Returns:
        The requested filter.

    Raises:
        HTTPException: If the filter does not exist.
    """
    filter_obj = crud.channel_filter.get_for_user(
        db, channel_filter_id, current_user.id
    )
    if not filter_obj:
        raise HTTPException(status_code=404, detail="Filter not found")
    return filter_obj


@router.put("/filters/{channel_filter_id}", response_model=Filter)
async def update_channel_filter(
    channel_filter_id: int,
    channel_filter: FilterUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Filter:
    """Update an existing channel filter.

    Args:
        channel_filter_id: Identifier of the filter to update.
        channel_filter: New filter values.
        db: Database session dependency.

    Returns:
        The updated filter instance.

    Raises:
        HTTPException: If the filter does not exist.
    """
    existing = crud.channel_filter.get_for_user(db, channel_filter_id, current_user.id)
    if not existing:
        raise HTTPException(status_code=404, detail="Filter not found")
    if channel_filter.channel_id is not None:
        channel = crud.channel.get_for_user(
            db, channel_filter.channel_id, current_user.id
        )
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
    updated = crud.channel_filter.update(db, channel_filter_id, channel_filter)
    if not updated:
        raise HTTPException(status_code=404, detail="Filter not found")
    return updated


@router.delete("/filters/{channel_filter_id}", response_model=Filter)
async def delete_channel_filter(
    channel_filter_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Filter:
    """Delete a channel filter.

    Args:
        channel_filter_id: Identifier of the filter to delete.
        db: Database session dependency.

    Returns:
        The deleted filter instance.

    Raises:
        HTTPException: If the filter does not exist.
    """
    existing = crud.channel_filter.get_for_user(db, channel_filter_id, current_user.id)
    if not existing:
        raise HTTPException(status_code=404, detail="Filter not found")
    deleted = crud.channel_filter.delete(db, channel_filter_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Filter not found")
    return deleted
