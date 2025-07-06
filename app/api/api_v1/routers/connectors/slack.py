from fastapi import APIRouter, Depends, Request
from app.connectors.slack_connector import SlackConnector
from app.core.config import get_settings, Settings

router = APIRouter()


def get_slack_connector(settings: Settings = Depends(get_settings)) -> SlackConnector:
    """Instantiate a Slack connector using app settings.

    Args:
        settings: Application settings dependency.

    Returns:
        Configured :class:`SlackConnector` instance.
    """

    return SlackConnector(
        token=settings.slack_token, channel_id=settings.slack_channel_id
    )


@router.post("/webhooks/slack")
async def process_slack_update(
    request: Request, slack_connector: SlackConnector = Depends(get_slack_connector)
):
    """Handle incoming Slack webhook events.

    Args:
        request: Incoming HTTP request containing the event payload.
        slack_connector: Dependency that processes the payload.

    Returns:
        A confirmation message once processed.
    """

    payload = await request.json()
    slack_connector.process_incoming(payload)
    return {"detail": "Update processed"}
