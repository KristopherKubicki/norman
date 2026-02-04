import hmac
import hashlib
import time
from fastapi import APIRouter, Depends, Request, HTTPException
from app.connectors.slack_connector import SlackConnector
from app.crud import connector as connector_crud
from app.core.config import get_settings, Settings
from app.api.deps import get_db
from app.routing.engine import enqueue_routing_job
from sqlalchemy.orm import Session

router = APIRouter()


def get_slack_connector(settings: Settings = Depends(get_settings)) -> SlackConnector:
    """Instantiate a Slack connector using app settings.

    Args:
        settings: Application settings dependency.

    Returns:
        Configured :class:`SlackConnector` instance.
    """

    return SlackConnector(
        token=settings.slack_token, channel_id=settings.slack_channel_id
    )


def _verify_slack_signature(
    *,
    signing_secret: str,
    body: bytes,
    timestamp: str,
    signature: str,
) -> None:
    if not signing_secret:
        raise HTTPException(status_code=400, detail="Slack signing secret not set")
    if not timestamp or not signature:
        raise HTTPException(status_code=400, detail="Missing Slack signature headers")

    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Slack timestamp") from exc

    if abs(time.time() - ts) > 60 * 5:
        raise HTTPException(status_code=400, detail="Stale Slack request")

    basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    digest = hmac.new(
        signing_secret.encode("utf-8"),
        basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    expected = f"v0={digest}"

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="Invalid Slack signature")


@router.post("/webhooks/slack")
async def process_slack_update(
    request: Request,
    slack_connector: SlackConnector = Depends(get_slack_connector),
    settings: Settings = Depends(get_settings),
):
    """Handle incoming Slack webhook events.

    Args:
        request: Incoming HTTP request containing the event payload.
        slack_connector: Dependency that processes the payload.

    Returns:
        A confirmation message once processed.
    """

    body = await request.body()
    _verify_slack_signature(
        signing_secret=settings.slack_signing_secret,
        body=body,
        timestamp=request.headers.get("X-Slack-Request-Timestamp", ""),
        signature=request.headers.get("X-Slack-Signature", ""),
    )

    payload = await request.json()
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    event = payload.get("event", payload)
    slack_connector.process_incoming(event)
    return {"detail": "Update processed"}


@router.post("/webhooks/slack/{connector_id}")
async def process_slack_update_for_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    connector = connector_crud.get(db, connector_id)
    if not connector or connector.connector_type != "slack":
        raise HTTPException(status_code=404, detail="Connector not found")

    config = connector.config or {}
    slack_connector = SlackConnector(
        token=config.get("token", ""),
        channel_id=config.get("channel_id", ""),
        config=config,
    )

    body = await request.body()
    _verify_slack_signature(
        signing_secret=config.get("signing_secret", ""),
        body=body,
        timestamp=request.headers.get("X-Slack-Request-Timestamp", ""),
        signature=request.headers.get("X-Slack-Signature", ""),
    )

    payload = await request.json()
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    event = payload.get("event", payload)
    normalized = slack_connector.process_incoming(event)
    await enqueue_routing_job(
        db=db, connector=connector, normalized=normalized, payload=payload
    )
    return {"detail": "Update processed"}
