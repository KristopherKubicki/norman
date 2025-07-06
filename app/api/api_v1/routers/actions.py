from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app import crud, schemas
from app.api.deps import get_db

router = APIRouter(prefix="/actions", tags=["actions"])


@router.post("/", response_model=schemas.Action)
def create_action(*, db: Session = Depends(get_db), action_in: schemas.ActionCreate):
    """Create a new action entry.

    Args:
        db: Database session dependency.
        action_in: Data used to create the action.

    Returns:
        The created action.
    """

    action = crud.action.create(db, obj_in=action_in)
    return action


@router.get("/{action_id}", response_model=schemas.Action)
def read_action(*, db: Session = Depends(get_db), action_id: int):
    """Retrieve an action by ID.

    Args:
        db: Database session dependency.
        action_id: Identifier of the action to fetch.

    Returns:
        The requested action.

    Raises:
        HTTPException: If the action does not exist.
    """

    action = crud.action.get(db, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    return action


@router.put("/{action_id}", response_model=schemas.Action)
def update_action(
    *, db: Session = Depends(get_db), action_id: int, action_in: schemas.ActionUpdate
):
    """Update an existing action.

    Args:
        db: Database session dependency.
        action_id: Identifier of the action to update.
        action_in: New values for the action.

    Returns:
        The updated action instance.

    Raises:
        HTTPException: If the action does not exist.
    """

    action = crud.action.get(db, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    action = crud.action.update(db, db_obj=action, obj_in=action_in)
    return action


@router.delete("/{action_id}", response_model=schemas.Action)
def delete_action(*, db: Session = Depends(get_db), action_id: int):
    """Remove an action by ID.

    Args:
        db: Database session dependency.
        action_id: Identifier of the action to delete.

    Returns:
        The deleted action instance.

    Raises:
        HTTPException: If the action does not exist.
    """

    action = crud.action.get(db, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    action = crud.action.remove(db, action_id)
    return action
