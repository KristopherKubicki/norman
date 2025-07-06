import socket
import ssl
import app.connectors.rfc5425_connector as mod


class DummySocket:
    def __init__(self):
        self.sent = []

    def sendall(self, data):
        self.sent.append(data)

    def close(self):
        pass


class DummyContext:
    def wrap_socket(self, sock, server_hostname=None):
        return sock


def test_send_message(monkeypatch):
    dummy = DummySocket()
    monkeypatch.setattr(socket, "create_connection", lambda addr: dummy)
    monkeypatch.setattr(ssl, "create_default_context", lambda: DummyContext())
    connector = mod.RFC5425Connector("host")
    connector.send_message("hi")
    assert dummy.sent[0].endswith(b"hi")
