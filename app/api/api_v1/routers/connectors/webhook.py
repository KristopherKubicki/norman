from fastapi import APIRouter, Depends, Request
from app.connectors.webhook_connector import WebhookConnector
from app.core.config import get_settings, Settings

router = APIRouter()

def get_webhook_connector(settings: Settings = Depends(get_settings)) -> WebhookConnector:
    return WebhookConnector(webhook_url=settings.webhook_secret)

@router.post("/webhooks/webhook")
async def process_webhook_update(request: Request, webhook_connector: WebhookConnector = Depends(get_webhook_connector)):
    payload = await request.json()
    webhook_connector.process_incoming(payload)
    return {"detail": "Update processed"}

