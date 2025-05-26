import sys
import types
import pytest

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
        def conversations_history(self, channel, limit=1):
            return {'messages': [{'text': 'hello', 'user': 'U1', 'channel': channel}]}
        def auth_test(self):
            return {'ok': True}

    slack_sdk.WebClient = DummyClient
    errors_mod = types.ModuleType('slack_sdk.errors')
    errors_mod.SlackApiError = SlackApiError
    slack_sdk.errors = errors_mod
    sys.modules['slack_sdk'] = slack_sdk
    sys.modules['slack_sdk.errors'] = errors_mod
else:
    from slack_sdk.errors import SlackApiError

from app.connectors.slack_connector import SlackConnector


def test_process_incoming():
    connector = SlackConnector(token='x', channel_id='C1')
    payload = {'text': 'hi', 'user': 'U1', 'channel': 'C1', 'ts': '1'}
    assert connector.process_incoming(payload) == payload


def test_receive_message_success():
    class DummyClient:
        def conversations_history(self, channel, limit=1):
            return {'messages': [{'text': 'hi', 'user': 'U1', 'channel': channel}]}
    connector = SlackConnector(token='x', channel_id='C1')
    connector.client = DummyClient()
    assert connector.receive_message() == [{'text': 'hi', 'user': 'U1', 'channel': 'C1'}]


def test_receive_message_error():
    class BadClient:
        def conversations_history(self, channel, limit=1):
            raise SlackApiError('error', {})
    connector = SlackConnector(token='x', channel_id='C1')
    connector.client = BadClient()
    assert connector.receive_message() == []


def test_listen_and_process():
    connector = SlackConnector(token='x', channel_id='C1')
    connector.receive_message = lambda: [{'text': 'hi', 'user': 'U1', 'channel': 'C1'}]
    results = connector.listen_and_process()
    assert results == [{'text': 'hi', 'user': 'U1', 'channel': 'C1', 'ts': None}]


def test_listen_and_process_error():
    connector = SlackConnector(token='x', channel_id='C1')

    def raise_error():
        raise SlackApiError('error', {})

    connector.receive_message = raise_error
    assert connector.listen_and_process() == []
