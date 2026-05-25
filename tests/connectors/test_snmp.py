import socket
import asyncio
import pytest

from app.connectors.snmp_connector import SNMPConnector


class DummySocket:
    def __init__(self):
        self.sent = []
        self.recv = [(b"hello", ("localhost", 9999))]
        self.bound = None

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def close(self):
        pass

    def bind(self, addr):
        self.bound = addr

    def setblocking(self, flag):
        pass

    def recvfrom(self, n):
        if self.recv:
            return self.recv.pop(0)
        raise BlockingIOError


def test_send_message_sender_mode(monkeypatch):
    dummy = DummySocket()
    monkeypatch.setattr(socket, "socket", lambda *a, **k: dummy)

    connector = SNMPConnector("example.com", port=162)  # non-local host => sender mode
    connector.connect()
    assert dummy.bound == ("", 0)

    connector.send_message("hi")
    assert dummy.sent == [(b"hi", ("example.com", 162))]


def test_listen_and_process_binds_listen_port(monkeypatch):
    dummy = DummySocket()
    monkeypatch.setattr(socket, "socket", lambda *a, **k: dummy)

    processed = []

    class TestConnector(SNMPConnector):
        async def process_incoming(self, message):
            processed.append(
                message.get("text") if isinstance(message, dict) else message
            )

    connector = TestConnector("0.0.0.0", port=1162)

    async def fake_sleep(t):
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.get_event_loop().run_until_complete(connector.listen_and_process())

    assert dummy.bound == ("0.0.0.0", 1162)
    assert processed == ["hello"]


def test_process_incoming_marks_passive():
    connector = SNMPConnector("0.0.0.0")
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming({"text": "trap text", "addr": ("1.2.3.4", 9999)})
    )
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "snmp"
