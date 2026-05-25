from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.connectors.whatsapp_connector import WhatsAppConnector
from app.crud import connector as connector_crud
from app.routing.engine import enqueue_routing_job

router = APIRouter()


@router.post("/webhooks/whatsapp/{connector_id}")
async def process_whatsapp_update_for_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    connector = connector_crud.get(db, connector_id)
    if not connector or connector.connector_type != "whatsapp":
        raise HTTPException(status_code=404, detail="Connector not found")

    config = connector.config or {}
    signature = request.headers.get("X-Twilio-Signature")
    form = await request.form()
    whatsapp_connector = WhatsAppConnector(
        account_sid=config.get("account_sid", ""),
        auth_token=config.get("auth_token", ""),
        from_number=config.get("from_number", ""),
        to_number=config.get("to_number", ""),
        status_callback_url=config.get("status_callback_url"),
        config=config,
    )
    if signature:
        if not whatsapp_connector.verify_signature(
            signature, str(request.url), dict(form)
        ):
            raise HTTPException(status_code=401, detail="Invalid Twilio signature")

    payload = dict(form)
    normalized = whatsapp_connector.process_incoming(payload)
    await enqueue_routing_job(
        db=db, connector=connector, normalized=normalized, payload=payload
    )
    return {"detail": "Update processed"}
