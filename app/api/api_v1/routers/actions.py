from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app import crud, schemas
from app.api.deps import get_db, get_current_user
from app.models import User

router = APIRouter(prefix="/actions", tags=["actions"])


@router.post("/", response_model=schemas.Action)
def create_action(
    *,
    db: Session = Depends(get_db),
    action_in: schemas.ActionCreate,
    current_user: User = Depends(get_current_user),
):
    """Create a new action entry.

    Args:
        db: Database session dependency.
        action_in: Data used to create the action.

    Returns:
        The created action.
    """

    filter_obj = crud.channel_filter.get_for_user(
        db, action_in.channel_filter_id, current_user.id
    )
    if not filter_obj:
        raise HTTPException(status_code=404, detail="Filter not found")
    if action_in.reply_channel_id is not None:
        reply_channel = crud.channel.get_for_user(
            db, action_in.reply_channel_id, current_user.id
        )
        if not reply_channel:
            raise HTTPException(status_code=404, detail="Channel not found")
    action = crud.action.create(db, obj_in=action_in)
    return action


@router.get("/{action_id}", response_model=schemas.Action)
def read_action(
    *,
    db: Session = Depends(get_db),
    action_id: int,
    current_user: User = Depends(get_current_user),
):
    """Retrieve an action by ID.

    Args:
        db: Database session dependency.
        action_id: Identifier of the action to fetch.

    Returns:
        The requested action.

    Raises:
        HTTPException: If the action does not exist.
    """

    action = crud.action.get_for_user(db, action_id, current_user.id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    return action


@router.put("/{action_id}", response_model=schemas.Action)
def update_action(
    *,
    db: Session = Depends(get_db),
    action_id: int,
    action_in: schemas.ActionUpdate,
    current_user: User = Depends(get_current_user),
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

    action = crud.action.get_for_user(db, action_id, current_user.id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    if action_in.channel_filter_id is not None:
        filter_obj = crud.channel_filter.get_for_user(
            db, action_in.channel_filter_id, current_user.id
        )
        if not filter_obj:
            raise HTTPException(status_code=404, detail="Filter not found")
    if action_in.reply_channel_id is not None:
        reply_channel = crud.channel.get_for_user(
            db, action_in.reply_channel_id, current_user.id
        )
        if not reply_channel:
            raise HTTPException(status_code=404, detail="Channel not found")
    action = crud.action.update(db, db_obj=action, obj_in=action_in)
    return action


@router.delete("/{action_id}", response_model=schemas.Action)
def delete_action(
    *,
    db: Session = Depends(get_db),
    action_id: int,
    current_user: User = Depends(get_current_user),
):
    """Remove an action by ID.

    Args:
        db: Database session dependency.
        action_id: Identifier of the action to delete.

    Returns:
        The deleted action instance.

    Raises:
        HTTPException: If the action does not exist.
    """

    action = crud.action.get_for_user(db, action_id, current_user.id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    action = crud.action.remove(db, action_id)
    return action
