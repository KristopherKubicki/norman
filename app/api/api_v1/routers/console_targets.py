from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import List, Optional

from app.api.deps import get_current_user, get_db
from app import crud
from app.models import User
from app.schemas.console_target import (
    ConsoleTargetCreate,
    ConsoleTargetOut,
    ConsoleTargetUpdate,
)

router = APIRouter(prefix="/console_targets", tags=["console_targets"])


def _get_user_target_or_404(db: Session, target_id: int, user: User):
    target = crud.console_target.get(db, target_id)
    if not target or target.user_id != user.id:
        raise HTTPException(status_code=404, detail="Console target not found")
    return target


@router.get("/", response_model=List[ConsoleTargetOut])
async def list_console_targets(
    response: Response,
    kind: Optional[str] = Query(None, max_length=32),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "private, max-age=5, stale-while-revalidate=10"
    items = crud.console_target.get_multi_by_user(db, current_user.id)
    if kind:
        want = kind.strip().lower()
        items = [t for t in items if (t.kind or "").strip().lower() == want]
    return items


@router.post("/", response_model=ConsoleTargetOut, status_code=201)
async def create_console_target(
    target: ConsoleTargetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if target.kind.strip().lower() != "tmux":
        raise HTTPException(status_code=400, detail="Unsupported kind")
    try:
        return crud.console_target.create(db, obj_in=target, user_id=current_user.id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A console target with that name already exists"
        )


@router.put("/{target_id}", response_model=ConsoleTargetOut)
async def update_console_target(
    target_id: int,
    target: ConsoleTargetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_obj = _get_user_target_or_404(db, target_id, current_user)
    try:
        return crud.console_target.update(db, db_obj=db_obj, obj_in=target)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A console target with that name already exists"
        )


@router.delete("/{target_id}", response_model=ConsoleTargetOut)
async def delete_console_target(
    target_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_obj = _get_user_target_or_404(db, target_id, current_user)
    deleted = crud.console_target.remove(db, target_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Console target not found")
    return deleted
