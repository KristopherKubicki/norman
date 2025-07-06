from fastapi import APIRouter, Depends, Request
from app.connectors.google_chat_connector import GoogleChatConnector
from app.core.config import get_settings, Settings

router = APIRouter()


def get_google_chat_connector(
    settings: Settings = Depends(get_settings),
) -> GoogleChatConnector:
    """Create a Google Chat connector.

    Args:
        settings: Application settings dependency.

    Returns:
        Configured :class:`GoogleChatConnector` instance.
    """

    return GoogleChatConnector(
        service_account_key_path=settings.google_chat_service_account_key_path,
        space=settings.google_chat_space,
    )


@router.post("/webhooks/google_chat")
async def process_google_chat_update(
    request: Request,
    google_chat_connector: GoogleChatConnector = Depends(get_google_chat_connector),
):
    """Handle Google Chat webhook events.

    Args:
        request: Incoming HTTP request containing the event payload.
        google_chat_connector: Dependency that processes the payload.

    Returns:
        A confirmation message once processed.
    """

    payload = await request.json()
    google_chat_connector.process_incoming(payload)
    return {"detail": "Update processed"}
