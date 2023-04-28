from fastapi import APIRouter, Depends, Request
from app.connectors.teams_connector import TeamsConnector
from app.core.config import get_settings, Settings

router = APIRouter()

def get_teams_connector(settings: Settings = Depends(get_settings)) -> TeamsConnector:
    return TeamsConnector(client_id=settings.teams_client_id, client_secret=settings.teams_client_secret, tenant_id=settings.teams_tenant_id)

@router.post("/webhooks/teams")
async def process_teams_update(request: Request, teams_connector: TeamsConnector = Depends(get_teams_connector)):
    payload = await request.json()
    teams_connector.process_incoming(payload)
    return {"detail": "Update processed"}

