from fastapi import APIRouter, Depends, Request
from app.connectors.rest_callback_connector import RestCallbackConnector
from app.core.config import get_settings, Settings

router = APIRouter()


def get_rest_callback_connector(settings: Settings = Depends(get_settings)) -> RestCallbackConnector:
    return RestCallbackConnector(
        inbound_url=settings.rest_callback_inbound_url,
        outbound_url=settings.rest_callback_outbound_url,
    )


@router.post("/webhooks/rest_callback")
async def process_rest_callback_update(
    request: Request,
    rest_connector: RestCallbackConnector = Depends(get_rest_callback_connector),
):
    payload = await request.json()
    await rest_connector.process_incoming(payload)
    return {"detail": "Update processed"}
