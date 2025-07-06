from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.api import deps

router = APIRouter(prefix="/filters", tags=["filters"])


@router.get("/", response_model=List[schemas.Filter])
def read_filters(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """Return multiple filters.

    Args:
        db: Database session dependency.
        skip: Number of records to skip.
        limit: Maximum number of records to return.

    Returns:
        A list of filters.
    """

    filters = crud.filters.get_multi(db, skip=skip, limit=limit)
    return filters


@router.post("/", response_model=schemas.Filter)
def create_filter(
    *, db: Session = Depends(deps.get_db), filter_in: schemas.FilterCreate
) -> Any:
    """Create a new filter.

    Args:
        db: Database session dependency.
        filter_in: Filter parameters.

    Returns:
        The created filter.
    """

    filter = crud.filters.create(db, filter_create=filter_in)
    return filter


@router.put("/{filter_id}", response_model=schemas.Filter)
def update_filter(
    *,
    db: Session = Depends(deps.get_db),
    filter_id: int,
    filter_in: schemas.FilterUpdate
) -> Any:
    """Update an existing filter.

    Args:
        db: Database session dependency.
        filter_id: Identifier of the filter to update.
        filter_in: New filter values.

    Returns:
        The updated filter instance.

    Raises:
        HTTPException: If the filter does not exist.
    """

    filter = crud.filters.get(db, filter_id)
    if not filter:
        raise HTTPException(status_code=404, detail="Filter not found")
    filter = crud.filters.update(db, filter_id=filter_id, filter_update=filter_in)
    return filter


@router.delete("/{filter_id}", response_model=schemas.Filter)
def delete_filter(*, db: Session = Depends(deps.get_db), filter_id: int) -> Any:
    """Delete a filter by ID.

    Args:
        db: Database session dependency.
        filter_id: Identifier of the filter to delete.

    Returns:
        The deleted filter instance.

    Raises:
        HTTPException: If the filter does not exist.
    """

    filter = crud.filters.get(db, filter_id)
    if not filter:
        raise HTTPException(status_code=404, detail="Filter not found")
    filter = crud.filters.remove(db, filter_id)
    return filter
