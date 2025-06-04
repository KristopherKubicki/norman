import asyncio
import types
import pytest

import app.connectors.tox_connector as mod


class DummyTox:
    def __init__(self):
        self.bootstrap_args = None
        self.friend_id = None
        self.sent = []
        self.callbacks = {}
        self.iterated = 0

    def bootstrap(self, host, port, key):
        self.bootstrap_args = (host, port, key)

    def add_friend(self, friend_id):
        self.friend_id = friend_id
        return 0

    def friend_send_message(self, friend_number, message):
        self.sent.append((friend_number, message))

    def callback_friend_message(self, cb):
        self.callbacks['friend_message'] = cb

    def iterate(self):
        self.iterated += 1
        if 'friend_message' in self.callbacks:
            self.callbacks['friend_message'](self, 0, 'hello')


def test_send_message(monkeypatch):
    dummy = DummyTox()
    monkeypatch.setattr(mod, 'toxcore', types.SimpleNamespace(Tox=lambda: dummy))
    connector = mod.ToxConnector('host', friend_id='id')
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message('hi')
    )
    assert result == 'sent'
    assert dummy.sent == [(0, 'hi')]
    assert connector.sent_messages == ['hi']
    assert dummy.bootstrap_args == ('host', 33445, 'id')


def test_no_library(monkeypatch):
    monkeypatch.setattr(mod, 'toxcore', None)
    connector = mod.ToxConnector('host')
    with pytest.raises(RuntimeError):
        asyncio.get_event_loop().run_until_complete(connector.send_message('hi'))


def test_listen_and_process(monkeypatch):
    dummy = DummyTox()
    monkeypatch.setattr(mod, 'toxcore', types.SimpleNamespace(Tox=lambda: dummy))

    processed = []

    class TestConnector(mod.ToxConnector):
        async def process_incoming(self, message):
            processed.append(message)

    connector = TestConnector('host', friend_id='id')

    async def fake_sleep(t):
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.get_event_loop().run_until_complete(connector.listen_and_process())

    assert processed == ['hello']
