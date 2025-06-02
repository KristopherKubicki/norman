from typing import List, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud, models
from app.schemas import FilterCreate, FilterUpdate, Filter
from app.api.deps import get_db

router = APIRouter()

@router.post("/filters/", response_model=Filter, status_code=status.HTTP_201_CREATED)  # type: ignore[misc]
async def create_channel_filter(
    channel_filter: FilterCreate, db: Session = Depends(get_db)
) -> Filter:
    """Create a new channel filter."""
    return crud.channel_filter.create(db, obj_in=channel_filter)

@router.get("/filters/", response_model=List[Filter])  # type: ignore[misc]
async def get_filters(db: Session = Depends(get_db)) -> List[Filter]:
    """Return all channel filters."""
    filters = db.query(models.Filter).all()
    return cast(List[Filter], filters)

@router.get("/filters/{channel_filter_id}", response_model=Filter)  # type: ignore[misc]
async def get_channel_filter(
    channel_filter_id: int, db: Session = Depends(get_db)
) -> Filter:
    """Return a channel filter by ID."""
    filter_obj = crud.channel_filter.get(db, channel_filter_id)
    if not filter_obj:
        raise HTTPException(status_code=404, detail="Filter not found")
    return filter_obj

@router.put("/filters/{channel_filter_id}", response_model=Filter)  # type: ignore[misc]
async def update_channel_filter(
    channel_filter_id: int,
    channel_filter: FilterUpdate,
    db: Session = Depends(get_db),
) -> Filter:
    """Update an existing channel filter."""
    updated = crud.channel_filter.update(db, channel_filter_id, channel_filter)
    if not updated:
        raise HTTPException(status_code=404, detail="Filter not found")
    return updated

@router.delete("/filters/{channel_filter_id}", response_model=Filter)  # type: ignore[misc]
async def delete_channel_filter(
    channel_filter_id: int, db: Session = Depends(get_db)
) -> Filter:
    """Delete a channel filter."""
    deleted = crud.channel_filter.delete(db, channel_filter_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Filter not found")
    return deleted

