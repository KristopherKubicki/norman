from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.crud import connector as connector_crud
from app.connectors.reddit_chat_connector import RedditChatConnector
from app.routing.engine import enqueue_routing_job

router = APIRouter()


@router.post("/webhooks/reddit/{connector_id}")
async def process_reddit_update_for_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    connector = connector_crud.get(db, connector_id)
    if not connector or connector.connector_type != "reddit_chat":
        raise HTTPException(status_code=404, detail="Connector not found")

    config = connector.config or {}
    payload = await request.json()
    reddit_connector = RedditChatConnector(
        client_id=config.get("client_id", ""),
        client_secret=config.get("client_secret", ""),
        username=config.get("username", ""),
        password=config.get("password", ""),
        user_agent=config.get("user_agent", "norman"),
        config=config,
    )
    normalized = reddit_connector.process_incoming(payload)
    await enqueue_routing_job(
        db=db, connector=connector, normalized=normalized, payload=payload
    )
    return {"detail": "Update processed"}
