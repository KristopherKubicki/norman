from typing import Any, List

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
) -> Any:
    filters = crud.filter.get_multi(db, skip=skip, limit=limit)
    return filters

@router.post("/", response_model=schemas.Filter)
def create_filter(
    *,
    db: Session = Depends(deps.get_db),
    filter_in: schemas.FilterCreate
) -> Any:
    filter = crud.filter.create(db, obj_in=filter_in)
    return filter

@router.put("/{filter_id}", response_model=schemas.Filter)
def update_filter(
    *,
    db: Session = Depends(deps.get_db),
    filter_id: int,
    filter_in: schemas.FilterUpdate
) -> Any:
    filter = crud.filter.get(db, filter_id)
    if not filter:
        raise HTTPException(status_code=404, detail="Filter not found")
    filter = crud.filter.update(db, db_obj=filter, obj_in=filter_in)
    return filter

@router.delete("/{filter_id}", response_model=schemas.Filter)
def delete_filter(
    *,
    db: Session = Depends(deps.get_db),
    filter_id: int
) -> Any:
    filter = crud.filter.get(db, filter_id)
    if not filter:
        raise HTTPException(status_code=404, detail="Filter not found")
    filter = crud.filter.remove(db, filter_id)
    return filter

