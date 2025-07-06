import socket
import asyncio
import pytest
from app.connectors.snmp_connector import SNMPConnector


class DummySocket:
    def __init__(self):
        self.sent = []
        self.recv = [b"hello"]

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def close(self):
        pass

    def bind(self, addr):
        pass

    def setblocking(self, flag):
        pass

    def recvfrom(self, n):
        if self.recv:
            return self.recv.pop(0), ("localhost", 0)
        raise BlockingIOError


def test_send_message(monkeypatch):
    dummy = DummySocket()
    monkeypatch.setattr(socket, "socket", lambda *a, **k: dummy)
    connector = SNMPConnector("host", port=162)
    connector.connect()
    connector.send_message("hi")
    assert dummy.sent == [(b"hi", ("host", 162))]


def test_listen_and_process(monkeypatch):
    dummy = DummySocket()
    monkeypatch.setattr(socket, "socket", lambda *a, **k: dummy)

    processed = []

    class TestConnector(SNMPConnector):
        async def process_incoming(self, message):
            processed.append(message)

    connector = TestConnector("host", port=162)

    async def fake_sleep(t):
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.get_event_loop().run_until_complete(connector.listen_and_process())

    assert processed == ["hello"]
