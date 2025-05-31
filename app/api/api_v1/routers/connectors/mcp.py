from fastapi import APIRouter, Depends, Request
from app.connectors.mcp_connector import MCPConnector
from app.core.config import get_settings, Settings

router = APIRouter()

def get_mcp_connector(settings: Settings = Depends(get_settings)) -> MCPConnector:
    return MCPConnector(api_url=settings.mcp_api_url, api_key=settings.mcp_api_key)

@router.post("/webhooks/mcp")
async def process_mcp_update(request: Request, mcp_connector: MCPConnector = Depends(get_mcp_connector)):
    payload = await request.json()
    await mcp_connector.process_incoming(payload)
    return {"detail": "Update processed"}
