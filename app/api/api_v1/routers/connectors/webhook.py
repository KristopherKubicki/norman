from fastapi import APIRouter, Depends, Request, HTTPException
from app.connectors.webhook_connector import WebhookConnector
from app.crud import connector as connector_crud
from app.core.config import get_settings, Settings
from app.api.deps import get_db
from app.routing.engine import enqueue_routing_job
from sqlalchemy.orm import Session

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

    return WebhookConnector(webhook_url=settings.webhook_url)


@router.post("/webhooks/webhook")
async def process_webhook_update(
    request: Request,
    webhook_connector: WebhookConnector = Depends(get_webhook_connector),
    settings: Settings = Depends(get_settings),
):
    """Handle simple webhook events.

    Args:
        request: Incoming HTTP request containing the event payload.
        webhook_connector: Dependency that processes the payload.

    Returns:
        A confirmation message once processed.
    """

    if settings.webhook_secret:
        secret = request.headers.get("X-Webhook-Secret")
        if secret != settings.webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    payload = await request.json()
    webhook_connector.process_incoming(payload)
    return {"detail": "Update processed"}


@router.post("/webhooks/webhook/{connector_id}")
async def process_webhook_update_for_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    connector = connector_crud.get(db, connector_id)
    if not connector or connector.connector_type != "webhook":
        raise HTTPException(status_code=404, detail="Connector not found")

    config = connector.config or {}
    expected_secret = config.get("secret") or config.get("webhook_secret")
    if expected_secret:
        secret = request.headers.get("X-Webhook-Secret")
        if secret != expected_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    webhook_url = config.get("webhook_url", "")
    webhook_connector = WebhookConnector(webhook_url=webhook_url, config=config)
    payload = await request.json()
    normalized = webhook_connector.process_incoming(payload)
    await enqueue_routing_job(
        db=db, connector=connector, normalized=normalized, payload=payload
    )
    return {"detail": "Update processed"}
