from fastapi import APIRouter, Depends, Request, Header, HTTPException
from app.connectors.webhook_connector import WebhookConnector
from app.core.config import get_settings, Settings

router = APIRouter()

def get_webhook_connector(settings: Settings = Depends(get_settings)) -> WebhookConnector:
    return WebhookConnector(webhook_url=settings.webhook_secret)

@router.post("/webhooks/webhook")
async def process_webhook_update(
    request: Request,
    webhook_connector: WebhookConnector = Depends(get_webhook_connector),
    x_webhook_token: str | None = Header(None),
    settings: Settings = Depends(get_settings),
):
    if settings.webhook_auth_token and x_webhook_token != settings.webhook_auth_token:
        raise HTTPException(status_code=401, detail="Invalid token")
    payload = await request.json()
    webhook_connector.process_incoming(payload)
    return {"detail": "Update processed"}

