from app.api.api_v1.routers.connectors.webhook import get_webhook_connector
from app.core.test_settings import TestSettings


def test_get_webhook_connector_uses_settings():
    connector = get_webhook_connector(TestSettings)
    assert connector.webhook_url == TestSettings.webhook_secret
