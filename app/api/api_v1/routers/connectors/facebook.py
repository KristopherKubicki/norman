from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.crud import connector as connector_crud
from app.connectors.facebook_messenger_connector import FacebookMessengerConnector
from app.routing.engine import enqueue_routing_job

router = APIRouter()


@router.post("/webhooks/facebook/{connector_id}")
async def process_facebook_update_for_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    connector = connector_crud.get(db, connector_id)
    if not connector or connector.connector_type != "facebook_messenger":
        raise HTTPException(status_code=404, detail="Connector not found")

    config = connector.config or {}
    expected = config.get("verify_token")
    if expected:
        token = request.query_params.get("hub.verify_token")
        if token and token != expected:
            raise HTTPException(status_code=401, detail="Invalid verify token")

    payload = await request.json()
    if isinstance(payload, dict):
        payload.setdefault(
            "_meta",
            {
                "headers": {k.lower(): v for k, v in request.headers.items()},
                "query": dict(request.query_params),
                "path": str(request.url.path),
            },
        )
    fb_connector = FacebookMessengerConnector(
        page_token=config.get("page_token", ""),
        verify_token=config.get("verify_token", ""),
        config=config,
    )
    normalized = fb_connector.process_incoming(payload)
    await enqueue_routing_job(
        db=db, connector=connector, normalized=normalized, payload=payload
    )
    return {"detail": "Update processed"}
