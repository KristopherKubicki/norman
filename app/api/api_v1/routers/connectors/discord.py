from fastapi import APIRouter, Depends, Request
from app.connectors.discord_connector import DiscordConnector
from app.core.config import get_settings, Settings

router = APIRouter()

def get_discord_connector(settings: Settings = Depends(get_settings)) -> DiscordConnector:
    """Instantiate :class:`DiscordConnector` using ``Settings`` values."""

    return DiscordConnector(
        token=settings.discord_token,
        channel_id=settings.discord_channel_id,
    )

@router.post("/webhooks/discord")
async def process_discord_update(request: Request, discord_connector: DiscordConnector = Depends(get_discord_connector)):
    payload = await request.json()
    discord_connector.process_incoming(payload)
    return {"detail": "Update processed"}

