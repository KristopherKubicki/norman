from fastapi import APIRouter, Depends, Request, HTTPException
from app.connectors.discord_connector import DiscordConnector
from app.crud import connector as connector_crud
from app.core.config import get_settings, Settings
from app.api.deps import get_db
from app.routing.engine import enqueue_routing_job
from sqlalchemy.orm import Session

router = APIRouter()


def get_discord_connector(
    settings: Settings = Depends(get_settings),
) -> DiscordConnector:
    """Build a Discord connector from settings.

    Args:
        settings: Application settings dependency.

    Returns:
        Configured :class:`DiscordConnector` instance.
    """

    return DiscordConnector(
        token=settings.discord_token,
        channel_id=settings.discord_channel_id,
        webhook_url=settings.discord_webhook_url,
    )


@router.post("/webhooks/discord")
async def process_discord_update(
    request: Request,
    discord_connector: DiscordConnector = Depends(get_discord_connector),
):
    """Handle incoming Discord webhook events.

    Args:
        request: Incoming request containing the event payload.
        discord_connector: Dependency that processes the payload.

    Returns:
        A confirmation message once processed.
    """

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
    discord_connector.process_incoming(payload)
    return {"detail": "Update processed"}


@router.post("/webhooks/discord/{connector_id}")
async def process_discord_update_for_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    connector = connector_crud.get(db, connector_id)
    if not connector or connector.connector_type != "discord":
        raise HTTPException(status_code=404, detail="Connector not found")

    config = connector.config or {}
    discord_connector = DiscordConnector(
        token=config.get("token"),
        channel_id=config.get("channel_id"),
        webhook_url=config.get("webhook_url"),
        config=config,
    )
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
    normalized = discord_connector.process_incoming(payload)
    await enqueue_routing_job(
        db=db, connector=connector, normalized=normalized, payload=payload
    )
    return {"detail": "Update processed"}
