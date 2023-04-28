from fastapi import APIRouter, Depends, Request
from app.connectors.webhook_connector import WebhookConnector

router = APIRouter()

def get_webhook_connector() -> WebhookConnector:
    return WebhookConnector()

@router.post("/webhooks/webhook")
async def process_webhook_update(request: Request, webhook_connector: WebhookConnector = Depends(get_webhook_connector)):
    payload = await request.json()
    webhook_connector.process_incoming(payload)
    return {"detail": "Update processed"}

