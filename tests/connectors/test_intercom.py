import requests
from app.connectors.intercom_connector import IntercomConnector

class DummyResponse:
    def __init__(self, text="ok", status=200):
        self.text = text
        self.status_code = status
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.RequestException("error")

def test_send_message_success(monkeypatch):
    def fake_post(url, json=None, headers=None):
        assert "api.intercom.io" in url
        return DummyResponse("sent")
    monkeypatch.setattr(requests, "post", fake_post)
    connector = IntercomConnector("TOKEN", "APP")
    assert connector.send_message("hi") == "sent"

def test_send_message_error(monkeypatch):
    def fake_post(url, json=None, headers=None):
        raise requests.RequestException("boom")
    monkeypatch.setattr(requests, "post", fake_post)
    connector = IntercomConnector("TOKEN", "APP")
    assert connector.send_message("hi") is None
