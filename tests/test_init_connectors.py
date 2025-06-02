import sys
import types
from fastapi import FastAPI

from app.connectors import init_connectors
from app.connectors.connector_utils import connector_classes
from app.core.test_settings import test_settings
from app.connectors.slack_connector import SlackConnector
from app.core.config import Settings

# Provide a minimal slack_sdk stub if the real package isn't installed
if 'slack_sdk' not in sys.modules:
    slack_sdk = types.ModuleType('slack_sdk')

    class DummyClient:
        def __init__(self, token=None):
            self.token = token
        def auth_test(self):
            return {'ok': True}
    slack_sdk.WebClient = DummyClient
    errors_mod = types.ModuleType('slack_sdk.errors')
    slack_sdk.errors = errors_mod
    sys.modules['slack_sdk'] = slack_sdk
    sys.modules['slack_sdk.errors'] = errors_mod


def test_init_connectors_adds_placeholders(monkeypatch):
    monkeypatch.setattr("app.connectors.get_settings", lambda: test_settings)
    monkeypatch.setattr("app.connectors.connector_utils.get_settings", lambda: test_settings)

    app = FastAPI()
    init_connectors(app, test_settings)
    assert hasattr(app.state, "connectors")
    assert set(app.state.connectors) == set(connector_classes)
    assert all(v == [] for v in app.state.connectors.values())


def test_init_connectors_with_slack(monkeypatch):
    settings = Settings(connectors=[{"type": "slack", "token": "x", "channel_id": "C1"}])

    monkeypatch.setattr("app.connectors.get_settings", lambda: settings)
    monkeypatch.setattr("app.connectors.connector_utils.get_settings", lambda: settings)

    app = FastAPI()
    init_connectors(app, settings)
    assert "slack" in app.state.connectors
    connector = app.state.connectors["slack"][0]
    assert isinstance(connector, SlackConnector)

