from fastapi import APIRouter, Depends, Request
from app.connectors.azure_eventgrid_connector import AzureEventGridConnector
from app.core.config import get_settings, Settings

router = APIRouter()


def get_eventgrid_connector(
    settings: Settings = Depends(get_settings),
) -> AzureEventGridConnector:
    """Create an Azure EventGrid connector.

    Args:
        settings: Application settings dependency.

    Returns:
        Configured :class:`AzureEventGridConnector` instance.
    """

    return AzureEventGridConnector(
        endpoint=settings.azure_eventgrid_endpoint,
        key=settings.azure_eventgrid_key,
    )


@router.post("/webhooks/eventgrid")
async def process_eventgrid_update(
    request: Request,
    eventgrid_connector: AzureEventGridConnector = Depends(get_eventgrid_connector),
):
    """Handle incoming EventGrid webhook events.

    Args:
        request: Incoming HTTP request with the event payload.
        eventgrid_connector: Dependency that processes the payload.

    Returns:
        A confirmation message once processed.
    """

    payload = await request.json()
    eventgrid_connector.process_incoming(payload)
    return {"detail": "Update processed"}
