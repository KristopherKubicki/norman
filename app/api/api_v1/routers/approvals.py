from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app import crud, models
from app.schemas.command_approval import CommandApprovalDecision, CommandApprovalOut
from app.connectors.connector_utils import get_connector
from app.core.config import get_settings
from app.core.safety_controls import execution_blocked_reason

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("/", response_model=list[CommandApprovalOut])
def list_approvals(
    status: str = Query("", description="Filter by status (pending/approved/etc.)"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return crud.command_approval.list_by_user(
        db, user_id=current_user.id, status=status, limit=limit
    )


@router.get("/count")
def count_approvals(
    status: str = Query("", description="Filter by status (pending/approved/etc.)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return {
        "count": crud.command_approval.count_by_user(
            db, user_id=current_user.id, status=status
        )
    }


@router.post("/{approval_id}/approve", response_model=CommandApprovalOut)
def approve(
    approval_id: int,
    body: CommandApprovalDecision,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    approval = crud.command_approval.get(db, approval_id)
    if not approval or approval.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=400, detail="Approval is not pending")

    if approval.command_class == "destructive":
        if not approval.confirm_token:
            raise HTTPException(status_code=400, detail="Missing confirm token")
        if (body.confirm_token or "").strip() != approval.confirm_token:
            raise HTTPException(status_code=400, detail="Confirm token mismatch")

    # Execute immediately on approve.
    app_settings = get_settings()
    blocked_reason = execution_blocked_reason(app_settings)
    if blocked_reason:
        # Record the decision but do not execute.
        approval = crud.command_approval.decide(
            db,
            approval=approval,
            status="approved",
            reason=(body.reason or blocked_reason),
        )
        return approval
    connector = (
        db.query(models.Connector)
        .filter(models.Connector.id == approval.connector_id)
        .first()
    )
    if not connector or connector.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Connector not found")

    instance = get_connector(connector.connector_type, connector.config or {})
    instance.send_message({"command": approval.command_text})

    approval = crud.command_approval.decide(
        db,
        approval=approval,
        status="executed",
        reason=(body.reason or "approved"),
    )
    return approval


@router.post("/{approval_id}/reject", response_model=CommandApprovalOut)
def reject(
    approval_id: int,
    body: CommandApprovalDecision,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    approval = crud.command_approval.get(db, approval_id)
    if not approval or approval.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=400, detail="Approval is not pending")

    approval = crud.command_approval.decide(
        db,
        approval=approval,
        status="rejected",
        reason=(body.reason or "rejected"),
    )
    return approval
