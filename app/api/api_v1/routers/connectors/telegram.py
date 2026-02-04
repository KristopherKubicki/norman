from fastapi import APIRouter, Depends, Request, HTTPException
from app.connectors.telegram_connector import TelegramConnector
from app.crud import connector as connector_crud
from app.core.config import get_settings, Settings
from app.api.deps import get_db
from app.routing.engine import enqueue_routing_job
from sqlalchemy.orm import Session

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


@router.post("/webhooks/telegram/{connector_id}")
async def process_telegram_update_for_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    connector = connector_crud.get(db, connector_id)
    if not connector or connector.connector_type != "telegram":
        raise HTTPException(status_code=404, detail="Connector not found")

    config = connector.config or {}
    expected_secret = (
        config.get("webhook_secret")
        or config.get("secret")
        or config.get("secret_token")
    )
    if expected_secret:
        header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if header != expected_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    telegram_connector = TelegramConnector(
        token=config.get("token", ""),
        chat_id=config.get("chat_id", ""),
        webhook_secret=expected_secret,
        config=config,
    )
    payload = await request.json()
    normalized = telegram_connector.process_incoming(payload)
    await enqueue_routing_job(
        db=db, connector=connector, normalized=normalized, payload=payload
    )
    return {"detail": "Update processed"}
