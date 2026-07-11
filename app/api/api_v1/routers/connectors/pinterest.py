from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.crud import connector as connector_crud
from app.connectors.pinterest_connector import PinterestConnector
from app.routing.engine import enqueue_routing_job

router = APIRouter()


@router.post("/webhooks/pinterest/{connector_id}")
async def process_pinterest_update_for_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    connector = connector_crud.get(db, connector_id)
    if not connector or connector.connector_type != "pinterest":
        raise HTTPException(status_code=404, detail="Connector not found")

    config = connector.config or {}
    payload = await request.json()
    pinterest_connector = PinterestConnector(
        access_token=config.get("access_token", ""),
        board_id=config.get("board_id", ""),
        config=config,
    )
    normalized = pinterest_connector.process_incoming(payload)
    await enqueue_routing_job(
        db=db, connector=connector, normalized=normalized, payload=payload
    )
    return {"detail": "Update processed"}
