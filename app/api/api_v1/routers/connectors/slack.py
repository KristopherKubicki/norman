from fastapi import APIRouter, Depends, Request
from typing import Dict
from app.connectors.slack_connector import SlackConnector
from app.core.config import get_settings, Settings

router = APIRouter()


def get_slack_connector(settings: Settings = Depends(get_settings)) -> SlackConnector:
    return SlackConnector(token=settings.slack_token, channel_id=settings.slack_channel_id)


@router.post("/webhooks/slack")  # type: ignore[misc]
async def process_slack_update(
    request: Request, slack_connector: SlackConnector = Depends(get_slack_connector)
) -> Dict[str, str]:
    payload = await request.json()
    slack_connector.process_incoming(payload)
    return {"detail": "Update processed"}
