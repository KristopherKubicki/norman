from app.api.api_v1.routers.connectors.webhook import get_webhook_connector
from app.core.test_settings import test_settings


def test_get_webhook_connector_uses_settings() -> None:
    """The dependency should build the connector using the provided settings."""
    connector = get_webhook_connector(test_settings)
    assert connector.webhook_url == test_settings.webhook_secret
