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
from app.connectors.mqtt_connector import MQTTConnector
from app.core.test_settings import TestSettings


def test_get_connector_returns_slack(monkeypatch):
    monkeypatch.setattr('app.connectors.connector_utils.get_settings', lambda: TestSettings)
    connector = get_connector('slack')
    assert isinstance(connector, SlackConnector)


def test_get_connector_returns_signal(monkeypatch):
    monkeypatch.setattr('app.connectors.connector_utils.get_settings', lambda: TestSettings)
    connector = get_connector('signal')
    assert isinstance(connector, SignalConnector)


def test_get_connector_returns_mqtt(monkeypatch):
    monkeypatch.setattr('app.connectors.connector_utils.get_settings', lambda: TestSettings)
    connector = get_connector('mqtt')
    assert isinstance(connector, MQTTConnector)


def test_get_connectors_data_missing_config(monkeypatch):
    monkeypatch.setattr('app.connectors.connector_utils.get_settings', lambda: TestSettings)
    data = get_connectors_data()
    assert all(item['status'] == 'missing_config' for item in data)
    slack_data = next(item for item in data if item['id'] == 'slack')
    assert slack_data['status'] == 'missing_config'
