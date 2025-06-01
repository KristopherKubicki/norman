import asyncio
import types
import pytest

import app.connectors.nats_connector as nats_connector

class DummyNATS:
    def __init__(self):
        self.published = []
        self.closed = False
    async def publish(self, subject, payload):
        self.published.append((subject, payload))
    async def drain(self):
        self.closed = True
    async def close(self):
        self.closed = True

async def fake_connect(servers=""):
    return DummyNATS()


def test_send_message(monkeypatch):
    dummy = DummyNATS()
    async def connect_stub(servers=""):
        return dummy
    monkeypatch.setattr(nats_connector, "nats", types.SimpleNamespace(connect=connect_stub))
    connector = nats_connector.NATSConnector(servers="nats://s", subject="sub")
    asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert dummy.published == [("sub", b"hi")]
    assert connector._nc is dummy


def test_no_library(monkeypatch):
    monkeypatch.setattr(nats_connector, "nats", None)
    connector = nats_connector.NATSConnector()
    with pytest.raises(RuntimeError):
        asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))

