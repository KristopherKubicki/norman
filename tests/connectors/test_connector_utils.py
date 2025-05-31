import sys
import types

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

from app.connectors.connector_utils import get_connector, get_connectors_data
from app.connectors.slack_connector import SlackConnector
from app.connectors.signal_connector import SignalConnector
from app.connectors.rest_callback_connector import RESTCallbackConnector
from app.connectors.mcp_connector import MCPConnector
from app.connectors.smtp_connector import SMTPConnector
from app.core.test_settings import TestSettings


def test_get_connector_returns_slack(monkeypatch):
    monkeypatch.setattr('app.connectors.connector_utils.get_settings', lambda: TestSettings)
    connector = get_connector('slack')
    assert isinstance(connector, SlackConnector)


def test_get_connector_returns_signal(monkeypatch):
    monkeypatch.setattr('app.connectors.connector_utils.get_settings', lambda: TestSettings)
    connector = get_connector('signal')
    assert isinstance(connector, SignalConnector)


def test_get_connector_returns_rest_callback(monkeypatch):
    monkeypatch.setattr('app.connectors.connector_utils.get_settings', lambda: TestSettings)
    connector = get_connector('rest_callback')
    assert isinstance(connector, RESTCallbackConnector)

def test_get_connector_returns_mcp(monkeypatch):
    monkeypatch.setattr('app.connectors.connector_utils.get_settings', lambda: TestSettings)
    connector = get_connector('mcp')
    assert isinstance(connector, MCPConnector)
def test_get_connector_returns_smtp(monkeypatch):
    monkeypatch.setattr('app.connectors.connector_utils.get_settings', lambda: TestSettings)
    connector = get_connector('smtp')
    assert isinstance(connector, SMTPConnector)


def test_get_connectors_data_missing_config(monkeypatch):
    monkeypatch.setattr('app.connectors.connector_utils.get_settings', lambda: TestSettings)
    data = get_connectors_data()
    assert all(item['status'] == 'missing_config' for item in data)
    slack_data = next(item for item in data if item['id'] == 'slack')
    assert slack_data['status'] == 'missing_config'
