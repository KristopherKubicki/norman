import sys
import types
from fastapi import FastAPI

from app.connectors import init_connectors
from app.connectors.connector_utils import connector_classes
from app.core.test_settings import test_settings
from app.connectors.slack_connector import SlackConnector
from app.core.config import Settings, load_config

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
    for name in connector_classes:
        attr = f"{name}_connector"
        assert hasattr(app.state, attr)
        assert getattr(app.state, attr) is None


def test_init_connectors_with_slack(monkeypatch):
    config = load_config()
    config["slack_token"] = "x"
    config["slack_channel_id"] = "C1"
    settings = Settings(**config)

    monkeypatch.setattr("app.connectors.get_settings", lambda: settings)
    monkeypatch.setattr("app.connectors.connector_utils.get_settings", lambda: settings)

    app = FastAPI()
    init_connectors(app, settings)
    for name in connector_classes:
        attr = f"{name}_connector"
        assert hasattr(app.state, attr)
    connector = getattr(app.state, "slack_connector")
    assert isinstance(connector, SlackConnector)

