import socket
import asyncio

from app.connectors.twitch_connector import TwitchConnector


class DummySocket:
    def __init__(self):
        self.sent = []
        self.to_recv = []
        self.closed = False

    def connect(self, addr):
        self.addr = addr

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, n):
        return self.to_recv.pop(0)

    def close(self):
        self.closed = True

    def getpeername(self):
        return ("host", 6667)


def make_connector(monkeypatch):
    sock = DummySocket()
    monkeypatch.setattr(socket, "socket", lambda *a, **k: sock)
    connector = TwitchConnector("token", "nick", "chan", server="irc.example.com")
    return connector, sock


def test_connect(monkeypatch):
    connector, sock = make_connector(monkeypatch)
    connector.connect()
    assert sock.sent[0] == b"PASS token\r\n"
    assert sock.sent[1] == b"NICK nick\r\n"
    assert sock.sent[2] == b"JOIN #chan\r\n"


def test_send_and_receive(monkeypatch):
    connector, sock = make_connector(monkeypatch)
    sock.to_recv = [b"PING :server\r\n", b":u!u@h PRIVMSG #chan :hello\r\n"]
    connector.connect()
    connector.send_message("hi")
    assert sock.sent[-1] == b"PRIVMSG #chan :hi\r\n"
    msg1 = connector.receive_message()
    assert msg1 == ""
    msg2 = connector.receive_message()
    assert msg2 == ":u!u@h PRIVMSG #chan :hello\r\n"
    assert sock.sent[-1] == b"PONG :server\r\n"


def test_disconnect(monkeypatch):
    connector, sock = make_connector(monkeypatch)
    connector.connect()
    connector.disconnect()
    assert sock.closed
    assert connector.socket is None


def test_is_connected(monkeypatch):
    connector, sock = make_connector(monkeypatch)
    connector.connect()
    assert connector.is_connected()
    connector.disconnect()
    assert not connector.is_connected()


def test_listen_and_process(monkeypatch):
    connector, sock = make_connector(monkeypatch)
    sock.to_recv = [b":u!u@h PRIVMSG #chan :hello\r\n"]
    connector.connect()
    result = asyncio.get_event_loop().run_until_complete(connector.listen_and_process())
    assert result == [{"raw": ":u!u@h PRIVMSG #chan :hello\r\n"}]


def test_listen_and_process_ping(monkeypatch):
    connector, sock = make_connector(monkeypatch)
    sock.to_recv = [b"PING :server\r\n"]
    connector.connect()
    result = asyncio.get_event_loop().run_until_complete(connector.listen_and_process())
    assert result == []
