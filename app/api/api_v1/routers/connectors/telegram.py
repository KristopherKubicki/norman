from fastapi import APIRouter, Depends, Request
from typing import Dict
from app.connectors.telegram_connector import TelegramConnector
from app.core.config import get_settings, Settings

router = APIRouter()

def get_telegram_connector(settings: Settings = Depends(get_settings)) -> TelegramConnector:
    return TelegramConnector(token=settings.telegram_token, chat_id=settings.telegram_chat_id)

@router.post("/webhooks/telegram")  # type: ignore[misc]
async def process_telegram_update(
    request: Request, telegram_connector: TelegramConnector = Depends(get_telegram_connector)
) -> Dict[str, str]:
    payload = await request.json()
    telegram_connector.process_incoming(payload)
    return {"detail": "Update processed"}
