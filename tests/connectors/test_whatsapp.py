import requests
from app.connectors.whatsapp_connector import WhatsAppConnector


class DummyResponse:
    def __init__(self, text="ok", status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("error")


def test_send_message_success(monkeypatch):
    def fake_post(url, data=None, auth=None):
        assert "Accounts" in url
        assert data["From"].startswith("whatsapp:")
        assert auth == ("SID", "TOKEN")
        return DummyResponse("sent")

    monkeypatch.setattr(requests, "post", fake_post)
    connector = WhatsAppConnector("SID", "TOKEN", "+1", "+2")
    assert connector.send_message("hi") == "sent"


def test_send_message_error(monkeypatch):
    def fake_post(url, data=None, auth=None):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "post", fake_post)
    connector = WhatsAppConnector("SID", "TOKEN", "+1", "+2")
    assert connector.send_message("hi") is None


import asyncio


def test_process_incoming():
    connector = WhatsAppConnector("SID", "TOKEN", "+1", "+2")
    payload = {"body": "hello"}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == payload
