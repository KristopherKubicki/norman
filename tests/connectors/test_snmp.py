import socket
from app.connectors.snmp_connector import SNMPConnector

class DummySocket:
    def __init__(self):
        self.sent = []
    def sendto(self, data, addr):
        self.sent.append((data, addr))
    def close(self):
        pass


def test_send_message(monkeypatch):
    dummy = DummySocket()
    monkeypatch.setattr(socket, "socket", lambda *a, **k: dummy)
    connector = SNMPConnector("host", port=162)
    connector.connect()
    connector.send_message("hi")
    assert dummy.sent == [(b"hi", ("host", 162))]
