from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.crud import connector as connector_crud
from app.connectors.instagram_dm_connector import InstagramDMConnector
from app.routing.engine import enqueue_routing_job

router = APIRouter()


@router.post("/webhooks/instagram/{connector_id}")
async def process_instagram_update_for_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    connector = connector_crud.get(db, connector_id)
    if not connector or connector.connector_type != "instagram_dm":
        raise HTTPException(status_code=404, detail="Connector not found")

    config = connector.config or {}
    payload = await request.json()
    instagram_connector = InstagramDMConnector(
        access_token=config.get("access_token", ""),
        user_id=config.get("user_id", ""),
        config=config,
    )
    normalized = instagram_connector.process_incoming(payload)
    await enqueue_routing_job(
        db=db, connector=connector, normalized=normalized, payload=payload
    )
    return {"detail": "Update processed"}
