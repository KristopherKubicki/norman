from fastapi import APIRouter, Depends, Request
from app.connectors.teams_connector import TeamsConnector
from app.core.config import get_settings, Settings

router = APIRouter()

def get_teams_connector(settings: Settings = Depends(get_settings)) -> TeamsConnector:
    return TeamsConnector(
        app_id=settings.teams_app_id,
        app_password=settings.teams_app_password,
        tenant_id=settings.teams_tenant_id,
        bot_endpoint=settings.teams_bot_endpoint,
    )

@router.post("/webhooks/teams")
async def process_teams_update(
    request: Request, teams_connector: TeamsConnector = Depends(get_teams_connector)
) -> dict[str, str]:
    payload = await request.json()
    teams_connector.process_incoming(payload)
    return {"detail": "Update processed"}

