from fastapi import APIRouter, Depends, Request
from app.connectors.mcp_connector import MCPConnector
from app.core.config import get_settings, Settings

router = APIRouter()


def get_mcp_connector(settings: Settings = Depends(get_settings)) -> MCPConnector:
    """Instantiate an MCP connector.

    Args:
        settings: Application settings dependency.

    Returns:
        Configured :class:`MCPConnector` instance.
    """

    return MCPConnector(api_url=settings.mcp_api_url, api_key=settings.mcp_api_key)


@router.post("/webhooks/mcp")
async def process_mcp_update(
    request: Request, mcp_connector: MCPConnector = Depends(get_mcp_connector)
):
    """Handle incoming MCP webhook events.

    Args:
        request: Incoming HTTP request containing the event payload.
        mcp_connector: Dependency that processes the payload.

    Returns:
        A confirmation message once processed.
    """

    payload = await request.json()
    await mcp_connector.process_incoming(payload)
    return {"detail": "Update processed"}
