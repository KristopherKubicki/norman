from fastapi import APIRouter, Depends, Request, HTTPException
from app.connectors.teams_connector import TeamsConnector
from app.crud import connector as connector_crud
from app.core.config import get_settings, Settings
from app.api.deps import get_db
from app.routing.engine import enqueue_routing_job
from sqlalchemy.orm import Session

router = APIRouter()


def get_teams_connector(settings: Settings = Depends(get_settings)) -> TeamsConnector:
    """Instantiate a Microsoft Teams connector.

    Args:
        settings: Application settings dependency.

    Returns:
        Configured :class:`TeamsConnector` instance.
    """

    return TeamsConnector(
        app_id=settings.teams_app_id,
        app_password=settings.teams_app_password,
        tenant_id=settings.teams_tenant_id,
        bot_endpoint=settings.teams_bot_endpoint,
        webhook_url=settings.teams_webhook_url,
        scope=settings.teams_scope,
    )


@router.post("/webhooks/teams")
async def process_teams_update(
    request: Request, teams_connector: TeamsConnector = Depends(get_teams_connector)
):
    """Handle Teams webhook events.

    Args:
        request: Incoming HTTP request containing the event payload.
        teams_connector: Dependency that processes the payload.

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
    teams_connector.process_incoming(payload)
    return {"detail": "Update processed"}


@router.post("/webhooks/teams/{connector_id}")
async def process_teams_update_for_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    connector = connector_crud.get(db, connector_id)
    if not connector or connector.connector_type != "teams":
        raise HTTPException(status_code=404, detail="Connector not found")

    config = connector.config or {}
    if config.get("secret"):
        if request.headers.get("X-Teams-Secret") != config.get("secret"):
            raise HTTPException(status_code=401, detail="Invalid Teams secret")

    teams_connector = TeamsConnector(
        app_id=config.get("app_id"),
        app_password=config.get("app_password"),
        tenant_id=config.get("tenant_id"),
        bot_endpoint=config.get("bot_endpoint"),
        webhook_url=config.get("webhook_url"),
        scope=config.get("scope"),
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
    normalized = teams_connector.process_incoming(payload)
    await enqueue_routing_job(
        db=db, connector=connector, normalized=normalized, payload=payload
    )
    return {"detail": "Update processed"}
