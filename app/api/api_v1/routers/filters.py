from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.api import deps

router = APIRouter()

@router.get("/", response_model=List[schemas.Filter])
def read_filters(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
) -> List[schemas.Filter]:
    filters = crud.filters.get_multi(db, skip=skip, limit=limit)
    return filters

@router.post("/", response_model=schemas.Filter)
def create_filter(
    *,
    db: Session = Depends(deps.get_db),
    filter_in: schemas.FilterCreate
) -> schemas.Filter:
    filter = crud.filters.create(db, filter_create=filter_in)
    return filter

@router.put("/{filter_id}", response_model=schemas.Filter)
def update_filter(
    *,
    db: Session = Depends(deps.get_db),
    filter_id: int,
    filter_in: schemas.FilterUpdate
) -> schemas.Filter:
    filter = crud.filters.get(db, filter_id)
    if not filter:
        raise HTTPException(status_code=404, detail="Filter not found")
    filter = crud.filters.update(db, filter_id=filter_id, filter_update=filter_in)
    return filter

@router.delete("/{filter_id}", response_model=schemas.Filter)
def delete_filter(
    *,
    db: Session = Depends(deps.get_db),
    filter_id: int
) -> schemas.Filter:
    filter = crud.filters.get(db, filter_id)
    if not filter:
        raise HTTPException(status_code=404, detail="Filter not found")
    filter = crud.filters.remove(db, filter_id)
    return filter

