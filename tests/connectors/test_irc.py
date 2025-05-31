import socket
import ssl
from app.connectors.irc_connector import IRCConnector

class DummySocket:
    def __init__(self):
        self.sent = []
        self.to_recv = [b"PING :server\r\n", b":u!u@h PRIVMSG #chan :hello\r\n"]
        self.closed = False
    def sendall(self, data):
        self.sent.append(data)
    def recv(self, n):
        return self.to_recv.pop(0)
    def close(self):
        self.closed = True
    def getpeername(self):
        return ("host", 6667)

class DummyContext:
    def __init__(self):
        self.wrapped = None
    def wrap_socket(self, sock, server_hostname=None):
        self.wrapped = sock
        return sock


def make_connector(monkeypatch, use_ssl=False):
    sock = DummySocket()
    monkeypatch.setattr(socket, "create_connection", lambda addr: sock)
    if use_ssl:
        monkeypatch.setattr(ssl, "create_default_context", lambda: DummyContext())
    connector = IRCConnector(
        server="irc.example.com",
        port=6667,
        nickname="nick",
        password="pass",
        channels=["#chan"],
        use_ssl=use_ssl,
    )
    return connector, sock


def test_connect(monkeypatch):
    connector, sock = make_connector(monkeypatch, use_ssl=True)
    connector.connect()
    assert sock.sent[0] == b"PASS pass\r\n"
    assert b"NICK nick" in sock.sent[1]
    assert b"USER nick" in sock.sent[2]
    assert b"JOIN #chan" in sock.sent[-1]


def test_send_and_receive(monkeypatch):
    connector, sock = make_connector(monkeypatch)
    connector.connect()
    connector.send_message("hi")
    assert sock.sent[-1] == b"PRIVMSG #chan :hi\r\n"
    message = connector.receive_message()
    assert message == ":u!u@h PRIVMSG #chan :hello\r\n"
    assert sock.sent[-1] == b"PONG :server\r\n"


def test_disconnect(monkeypatch):
    connector, sock = make_connector(monkeypatch)
    connector.connect()
    connector.disconnect()
    assert sock.closed
    assert connector.socket is None


def test_is_connected(monkeypatch):
    connector, _ = make_connector(monkeypatch)
    connector.connect()
    assert connector.is_connected()
    connector.disconnect()
    assert not connector.is_connected()
