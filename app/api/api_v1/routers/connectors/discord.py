from fastapi import APIRouter, Depends, Request
from app.connectors.discord_connector import DiscordConnector
from app.core.config import get_settings, Settings

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
    discord_connector.process_incoming(payload)
    return {"detail": "Update processed"}
