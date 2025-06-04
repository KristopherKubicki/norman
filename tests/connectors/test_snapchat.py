import sys
import types
import asyncio

# Provide a minimal snapchat stub if the real package isn't installed
if "snapchat" not in sys.modules:
    snapchat = types.ModuleType("snapchat")

    class SnapchatError(Exception):
        pass

    class DummyClient:
        def __init__(self, username, password):
            self.username = username
            self.password = password
            self.sent = []
            self.messages = []
            self.raise_on_send = False
            self.raise_on_messages = False
            self.logged_in_state = True

        def send(self, to, text):
            if self.raise_on_send:
                raise SnapchatError("boom")
            self.sent.append((to, text))
            return "ok"

        def get_messages(self):
            if self.raise_on_messages:
                raise SnapchatError("boom")
            return self.messages

        def logged_in(self):
            return self.logged_in_state

    snapchat.Client = DummyClient
    snapchat.SnapchatError = SnapchatError
    sys.modules["snapchat"] = snapchat
else:
    import snapchat

from app.connectors.snapchat_connector import SnapchatConnector


def test_send_message_success():
    connector = SnapchatConnector("user", "pw", "friend")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"
    assert connector._get_client().sent == [("friend", "hi")]


def test_send_message_error():
    connector = SnapchatConnector("user", "pw", "friend")
    client = connector._get_client()
    client.raise_on_send = True
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result is None


def test_process_incoming():
    connector = SnapchatConnector("user", "pw", "friend")
    result = asyncio.get_event_loop().run_until_complete(connector.process_incoming({"m": 1}))
    assert result == {"m": 1}


def test_is_connected_success():
    connector = SnapchatConnector("user", "pw", "friend")
    assert connector.is_connected()


def test_is_connected_error():
    connector = SnapchatConnector("user", "pw", "friend")
    client = connector._get_client()
    client.logged_in_state = False
    assert not connector.is_connected()


def test_listen_and_process():
    connector = SnapchatConnector("user", "pw", "friend")
    client = connector._get_client()
    client.messages = [{"text": "hello"}]
    results = asyncio.get_event_loop().run_until_complete(connector.listen_and_process())
    assert results == [{"text": "hello"}]


def test_listen_and_process_error():
    connector = SnapchatConnector("user", "pw", "friend")
    client = connector._get_client()
    client.raise_on_messages = True
    results = asyncio.get_event_loop().run_until_complete(connector.listen_and_process())
    assert results == []
