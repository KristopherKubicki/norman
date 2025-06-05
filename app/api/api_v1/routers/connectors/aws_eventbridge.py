from fastapi import APIRouter, Depends, Request
from app.connectors.aws_eventbridge_connector import AWSEventBridgeConnector
from app.core.config import get_settings, Settings

router = APIRouter()


def get_eventbridge_connector(settings: Settings = Depends(get_settings)) -> AWSEventBridgeConnector:
    return AWSEventBridgeConnector(
        region=settings.aws_eventbridge_region,
        event_bus_name=settings.aws_eventbridge_event_bus_name,
    )


@router.post("/webhooks/eventbridge")
async def process_eventbridge_update(
    request: Request,
    eventbridge_connector: AWSEventBridgeConnector = Depends(get_eventbridge_connector),
):
    payload = await request.json()
    eventbridge_connector.process_incoming(payload)
    return {"detail": "Update processed"}
