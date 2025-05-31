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

# Provide a minimal mastodon stub if the real package isn't installed
if 'mastodon' not in sys.modules:
    mastodon_mod = types.ModuleType('mastodon')

    class DummyMastodon:
        def __init__(self, access_token=None, api_base_url=None):
            self.access_token = access_token
            self.api_base_url = api_base_url

        def status_post(self, status):
            return {'content': status}

    mastodon_mod.Mastodon = DummyMastodon
    sys.modules['mastodon'] = mastodon_mod

from app.connectors.connector_utils import get_connector, get_connectors_data
from app.connectors.slack_connector import SlackConnector
from app.connectors.mastodon_connector import MastodonConnector
from app.core.test_settings import TestSettings


def test_get_connector_returns_slack(monkeypatch):
    monkeypatch.setattr('app.connectors.connector_utils.get_settings', lambda: TestSettings)
    connector = get_connector('slack')
    assert isinstance(connector, SlackConnector)


def test_get_connector_returns_mastodon(monkeypatch):
    monkeypatch.setattr('app.connectors.connector_utils.get_settings', lambda: TestSettings)
    connector = get_connector('mastodon')
    assert isinstance(connector, MastodonConnector)


def test_get_connectors_data_missing_config(monkeypatch):
    monkeypatch.setattr('app.connectors.connector_utils.get_settings', lambda: TestSettings)
    data = get_connectors_data()
    assert all(item['status'] == 'missing_config' for item in data)
    slack_data = next(item for item in data if item['id'] == 'slack')
    assert slack_data['status'] == 'missing_config'
