from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.crud import connector as connector_crud
from app.connectors.linkedin_connector import LinkedInConnector
from app.routing.engine import enqueue_routing_job

router = APIRouter()


@router.post("/webhooks/linkedin/{connector_id}")
async def process_linkedin_update_for_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    connector = connector_crud.get(db, connector_id)
    if not connector or connector.connector_type != "linkedin":
        raise HTTPException(status_code=404, detail="Connector not found")

    config = connector.config or {}
    payload = await request.json()
    linkedin_connector = LinkedInConnector(
        access_token=config.get("access_token", ""),
        config=config,
    )
    normalized = linkedin_connector.process_incoming(payload)
    await enqueue_routing_job(
        db=db, connector=connector, normalized=normalized, payload=payload
    )
    return {"detail": "Update processed"}
