from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
import asyncio

from app.api.deps import get_db
from app.connectors.connector_utils import get_connector
from app.crud import connector as connector_crud
from app.routing.engine import enqueue_routing_job

router = APIRouter()


@router.post("/webhooks/{connector_type}/{connector_id}")
async def process_generic_update_for_connector(
    connector_type: str,
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Generic webhook handler for connectors backed by stored config."""

    connector = connector_crud.get(db, connector_id)
    if not connector or connector.connector_type != connector_type:
        raise HTTPException(status_code=404, detail="Connector not found")

    try:
        payload = await request.json()
    except Exception:
        body = await request.body()
        payload = body.decode("utf-8", errors="replace")

    if isinstance(payload, dict):
        payload.setdefault(
            "_meta",
            {
                "headers": {k.lower(): v for k, v in request.headers.items()},
                "query": dict(request.query_params),
                "path": str(request.url.path),
            },
        )

    config = connector.config or {}
    try:
        instance = get_connector(connector.connector_type, config)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    normalized = instance.process_incoming(payload)
    if asyncio.iscoroutine(normalized):
        normalized = await normalized

    await enqueue_routing_job(
        db=db,
        connector=connector,
        normalized=normalized if isinstance(normalized, dict) else {},
        payload=payload,
    )
    return {"status": "ok"}
