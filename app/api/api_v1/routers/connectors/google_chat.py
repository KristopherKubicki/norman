from fastapi import APIRouter, Depends, Request, HTTPException

try:  # optional dependency
    from app.connectors.google_chat_connector import GoogleChatConnector
except Exception:  # pragma: no cover - optional dependency missing
    GoogleChatConnector = None  # type: ignore
from app.crud import connector as connector_crud
from app.core.config import get_settings, Settings
from app.api.deps import get_db
from app.routing.engine import enqueue_routing_job
from sqlalchemy.orm import Session

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

    if GoogleChatConnector is None:
        raise HTTPException(status_code=503, detail="Google Chat connector unavailable")
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
    if isinstance(payload, dict):
        payload.setdefault(
            "_meta",
            {
                "headers": {k.lower(): v for k, v in request.headers.items()},
                "query": dict(request.query_params),
                "path": str(request.url.path),
            },
        )
    google_chat_connector.process_incoming(payload)
    return {"detail": "Update processed"}


@router.post("/webhooks/google_chat/{connector_id}")
async def process_google_chat_update_for_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    connector = connector_crud.get(db, connector_id)
    if not connector or connector.connector_type != "google_chat":
        raise HTTPException(status_code=404, detail="Connector not found")

    config = connector.config or {}
    if config.get("verification_token"):
        if request.headers.get("X-Goog-Chat-Token") != config.get("verification_token"):
            raise HTTPException(status_code=401, detail="Invalid verification token")

    if GoogleChatConnector is None:
        raise HTTPException(status_code=503, detail="Google Chat connector unavailable")
    google_chat_connector = GoogleChatConnector(
        service_account_key_path=config.get("service_account_key_path", ""),
        space=config.get("space", ""),
        config=config,
    )
    payload = await request.json()
    if isinstance(payload, dict):
        payload.setdefault(
            "_meta",
            {
                "headers": {k.lower(): v for k, v in request.headers.items()},
                "query": dict(request.query_params),
                "path": str(request.url.path),
            },
        )
    normalized = google_chat_connector.process_incoming(payload)
    await enqueue_routing_job(
        db=db, connector=connector, normalized=normalized, payload=payload
    )
    return {"detail": "Update processed"}
