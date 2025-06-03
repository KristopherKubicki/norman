from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app import crud, schemas
from app.api.deps import get_db

router = APIRouter(prefix="/actions", tags=["actions"])

@router.post("/", response_model=schemas.Action)
def create_action(
    *,
    db: Session = Depends(get_db),
    action_in: schemas.ActionCreate
):
    action = crud.action.create(db, obj_in=action_in)
    return action

@router.get("/{action_id}", response_model=schemas.Action)
def read_action(
    *,
    db: Session = Depends(get_db),
    action_id: int
):
    action = crud.action.get(db, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    return action

@router.put("/{action_id}", response_model=schemas.Action)
def update_action(
    *,
    db: Session = Depends(get_db),
    action_id: int,
    action_in: schemas.ActionUpdate
):
    action = crud.action.get(db, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    action = crud.action.update(db, db_obj=action, obj_in=action_in)
    return action

@router.delete("/{action_id}", response_model=schemas.Action)
def delete_action(
    *,
    db: Session = Depends(get_db),
    action_id: int
):
    action = crud.action.get(db, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    action = crud.action.remove(db, action_id)
    return action

