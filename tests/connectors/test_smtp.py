import asyncio
import types

import app.connectors.smtp_connector as smtp_connector


class DummySMTP:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.tls = False
        self.logged_in = False
        self.sent = None
        self.quit_called = False

    def starttls(self):
        self.tls = True

    def login(self, user, password):
        self.logged_in = True
        self.user = user
        self.password = password

    def send_message(self, msg):
        self.sent = msg

    def quit(self):
        self.quit_called = True


def test_send_and_disconnect(monkeypatch):
    monkeypatch.setattr(
        smtp_connector, "smtplib", types.SimpleNamespace(SMTP=DummySMTP)
    )
    connector = smtp_connector.SMTPConnector(
        host="localhost",
        port=25,
        username="u",
        password="p",
        from_address="a@example.com",
        to_address="b@example.com",
    )
    asyncio.get_event_loop().run_until_complete(connector.send_message("hello"))
    server = connector.server
    assert isinstance(server, DummySMTP)
    assert server.sent.get_content().strip() == "hello"
    assert connector.is_connected()
    connector.disconnect()
    assert server.quit_called
    assert not connector.is_connected()


def test_process_incoming():
    connector = smtp_connector.SMTPConnector("h")
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming("x")
    )
    assert result == "x"
