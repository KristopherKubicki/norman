from fastapi import APIRouter, Depends, Request
from app.connectors.webhook_connector import WebhookConnector
from app.core.config import get_settings, Settings

router = APIRouter()


def get_webhook_connector(
    settings: Settings = Depends(get_settings),
) -> WebhookConnector:
    """Create a generic webhook connector.

    Args:
        settings: Application settings dependency.

    Returns:
        Configured :class:`WebhookConnector` instance.
    """

    return WebhookConnector(webhook_url=settings.webhook_secret)


@router.post("/webhooks/webhook")
async def process_webhook_update(
    request: Request,
    webhook_connector: WebhookConnector = Depends(get_webhook_connector),
):
    """Handle simple webhook events.

    Args:
        request: Incoming HTTP request containing the event payload.
        webhook_connector: Dependency that processes the payload.

    Returns:
        A confirmation message once processed.
    """

    payload = await request.json()
    webhook_connector.process_incoming(payload)
    return {"detail": "Update processed"}
