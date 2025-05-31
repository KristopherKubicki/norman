import sys
import types

# Provide a minimal slack_sdk stub if the real package isn't installed
if 'slack_sdk' not in sys.modules:
    slack_sdk = types.ModuleType('slack_sdk')

    class SlackApiError(Exception):
        def __init__(self, message=None, response=None):
            super().__init__(message)
            self.response = response

    class DummyClient:
        def __init__(self, token=None):
            self.token = token

    slack_sdk.WebClient = DummyClient
    errors_mod = types.ModuleType('slack_sdk.errors')
    errors_mod.SlackApiError = SlackApiError
    slack_sdk.errors = errors_mod
    sys.modules['slack_sdk'] = slack_sdk
    sys.modules['slack_sdk.errors'] = errors_mod

from app.api.api_v1.routers.connectors.slack import get_slack_connector
from app.core.test_settings import TestSettings


def test_get_slack_connector_uses_settings():
    connector = get_slack_connector(TestSettings)
    assert connector.token == TestSettings.slack_token
    assert connector.channel_id == TestSettings.slack_channel_id
