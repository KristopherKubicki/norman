import sys
import types
from fastapi.testclient import TestClient

# Provide a minimal slack_sdk stub if the real package isn't installed
if "slack_sdk" not in sys.modules:
    slack_sdk = types.ModuleType("slack_sdk")

    class SlackApiError(Exception):
        def __init__(self, message=None, response=None):
            super().__init__(message)
            self.response = response

    class DummyClient:
        def __init__(self, token=None):
            self.token = token

    slack_sdk.WebClient = DummyClient
    errors_mod = types.ModuleType("slack_sdk.errors")
    errors_mod.SlackApiError = SlackApiError
    slack_sdk.errors = errors_mod
    sys.modules["slack_sdk"] = slack_sdk
    sys.modules["slack_sdk.errors"] = errors_mod

from app.api.api_v1.routers.connectors.slack import get_slack_connector
from app.core.test_settings import test_settings


def test_get_slack_connector_uses_settings():
    connector = get_slack_connector(test_settings)
    assert connector.token == test_settings.slack_token
    assert connector.channel_id == test_settings.slack_channel_id


def test_process_slack_update_endpoint(monkeypatch, test_app: TestClient):
    received = {}

    class DummyConnector:
        def process_incoming(self, payload):
            received["payload"] = payload

    test_app.app.dependency_overrides[get_slack_connector] = lambda: DummyConnector()
    payload = {"text": "hello"}
    resp = test_app.post("/api/v1/connectors/slack/webhooks/slack", json=payload)

    assert resp.status_code == 200
    assert received["payload"] == payload

    test_app.app.dependency_overrides = {}
