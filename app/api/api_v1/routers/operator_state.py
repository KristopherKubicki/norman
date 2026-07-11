from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models import User
from app.schemas.operator_state import OperatorStateOut
from app.services.operator_state import build_operator_state

router = APIRouter(prefix="/operator-state", tags=["operator_state"])


@router.get("/current", response_model=OperatorStateOut)
async def get_operator_state_current(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return build_operator_state(db, user_id=current_user.id)
