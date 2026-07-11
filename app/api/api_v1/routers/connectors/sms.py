import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.connectors.sms_connector import SMSConnector
from app.crud import connector as connector_crud
from app.routing.engine import enqueue_routing_job

router = APIRouter()


@router.post("/webhooks/sms/{connector_id}")
async def process_sms_update_for_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    connector = connector_crud.get(db, connector_id)
    if not connector or connector.connector_type != "sms":
        raise HTTPException(status_code=404, detail="Connector not found")

    config = connector.config or {}
    signature = request.headers.get("X-Twilio-Signature")
    form = await request.form()
    payload = dict(form)

    sms_connector = SMSConnector(
        account_sid=config.get("account_sid", ""),
        auth_token=config.get("auth_token", ""),
        from_number=config.get("from_number", ""),
        to_number=config.get("to_number", ""),
        config=config,
    )
    if signature and not sms_connector.verify_signature(
        signature, str(request.url), payload
    ):
        raise HTTPException(status_code=401, detail="Invalid Twilio signature")

    normalized = sms_connector.process_incoming(payload)
    if asyncio.iscoroutine(normalized):
        normalized = await normalized

    await enqueue_routing_job(
        db=db, connector=connector, normalized=normalized, payload=payload
    )
    return {"detail": "Update processed"}
