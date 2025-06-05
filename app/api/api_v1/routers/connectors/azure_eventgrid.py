from fastapi import APIRouter, Depends, Request
from app.connectors.azure_eventgrid_connector import AzureEventGridConnector
from app.core.config import get_settings, Settings

router = APIRouter()


def get_eventgrid_connector(settings: Settings = Depends(get_settings)) -> AzureEventGridConnector:
    return AzureEventGridConnector(
        endpoint=settings.azure_eventgrid_endpoint,
        key=settings.azure_eventgrid_key,
    )


@router.post("/webhooks/eventgrid")
async def process_eventgrid_update(
    request: Request,
    eventgrid_connector: AzureEventGridConnector = Depends(get_eventgrid_connector),
):
    payload = await request.json()
    eventgrid_connector.process_incoming(payload)
    return {"detail": "Update processed"}
