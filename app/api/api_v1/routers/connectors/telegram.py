from fastapi import APIRouter, Depends, Request
from app.connectors.telegram_connector import TelegramConnector
from app.core.config import get_settings, Settings

router = APIRouter()


def get_telegram_connector(
    settings: Settings = Depends(get_settings),
) -> TelegramConnector:
    """Instantiate a Telegram connector.

    Args:
        settings: Application settings dependency.

    Returns:
        Configured :class:`TelegramConnector` instance.
    """

    return TelegramConnector(
        token=settings.telegram_token, chat_id=settings.telegram_chat_id
    )


@router.post("/webhooks/telegram")
async def process_telegram_update(
    request: Request,
    telegram_connector: TelegramConnector = Depends(get_telegram_connector),
):
    """Handle Telegram webhook events.

    Args:
        request: Incoming HTTP request containing the event payload.
        telegram_connector: Dependency that processes the payload.

    Returns:
        A confirmation message once processed.
    """

    payload = await request.json()
    telegram_connector.process_incoming(payload)
    return {"detail": "Update processed"}
