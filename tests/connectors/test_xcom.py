import sys
import types
import asyncio
import pytest

# Provide a minimal tweepy stub if the real package isn't installed
if "tweepy" not in sys.modules:
    tweepy = types.ModuleType("tweepy")

    class TweepyException(Exception):
        pass

    class DummyAuth:
        def __init__(self, *args, **kwargs):
            pass

    class DummyAPI:
        def __init__(self, auth=None):
            self.auth = auth
            self.sent = []
            self.messages = []
            self.raise_on_send = False
            self.raise_on_verify = False
            self.raise_on_list = False

        def send_direct_message(self, recipient_id, text=None):
            if self.raise_on_send:
                raise TweepyException("boom")
            self.sent.append((recipient_id, text))
            return {"event_id": "1"}

        def list_direct_messages(self):
            if self.raise_on_list:
                raise TweepyException("fail")
            return self.messages

        def verify_credentials(self):
            if self.raise_on_verify:
                raise TweepyException("bad auth")
            return True

    tweepy.API = DummyAPI
    tweepy.OAuth1UserHandler = DummyAuth
    tweepy.TweepyException = TweepyException
    sys.modules["tweepy"] = tweepy
else:
    import tweepy

from app.connectors.xcom_connector import XComConnector


def test_send_message_success():
    connector = XComConnector("k", "s", "at", "ats", "1")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"
    assert connector._get_client().sent == [("1", "hi")]


def test_send_message_error():
    connector = XComConnector("k", "s", "at", "ats", "1")
    client = connector._get_client()
    client.raise_on_send = True
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result is None


def test_process_incoming():
    connector = XComConnector("k", "s", "at", "ats", "1")
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming({"msg": 1})
    )
    assert result == {"msg": 1}


def test_is_connected_success():
    connector = XComConnector("k", "s", "at", "ats", "1")
    assert connector.is_connected()


def test_is_connected_error():
    connector = XComConnector("k", "s", "at", "ats", "1")
    client = connector._get_client()
    client.raise_on_verify = True
    assert not connector.is_connected()


def test_listen_and_process(monkeypatch):
    connector = XComConnector("k", "s", "at", "ats", "1")
    client = connector._get_client()
    client.messages = [{"id": "1", "text": "hello"}]

    processed = []

    async def _process(msg):
        processed.append(msg)

    connector.process_incoming = _process

    async def stop(_):
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", stop)

    with pytest.raises(asyncio.CancelledError):
        asyncio.get_event_loop().run_until_complete(connector.listen_and_process())

    assert processed == [{"id": "1", "text": "hello"}]
