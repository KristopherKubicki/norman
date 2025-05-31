import asyncio
import smtplib
from app.connectors.smtp_connector import SMTPConnector


class DummySMTP:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sent = False

    def starttls(self):
        pass

    def login(self, username, password):
        self.username = username
        self.password = password

    def sendmail(self, from_addr, to_addrs, msg):
        self.sent = True
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        pass


def test_send_message(monkeypatch):
    dummy = DummySMTP('host', 587)
    monkeypatch.setattr(smtplib, 'SMTP', lambda h, p: dummy)
    connector = SMTPConnector(
        host='host',
        port=587,
        username='u',
        password='p',
        from_addr='a@example.com',
        to_addr='b@example.com',
    )
    asyncio.run(connector.send_message({'text': 'hi'}))
    assert dummy.sent
