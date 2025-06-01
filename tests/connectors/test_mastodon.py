import requests
from app.connectors.mastodon_connector import MastodonConnector

class DummyResponse:
    def __init__(self, text="ok", status=200):
        self.text = text
        self.status_code = status
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.RequestException("error")

def test_send_message_success(monkeypatch):
    def fake_post(url, headers=None, data=None):
        assert "/api/v1/statuses" in url
        return DummyResponse("sent")
    monkeypatch.setattr(requests, "post", fake_post)
    connector = MastodonConnector("http://host", "TOKEN")
    assert connector.send_message("hi") == "sent"

def test_send_message_error(monkeypatch):
    def fake_post(url, headers=None, data=None):
        raise requests.RequestException("boom")
    monkeypatch.setattr(requests, "post", fake_post)
    connector = MastodonConnector("http://host", "TOKEN")
    assert connector.send_message("hi") is None


def test_is_connected_success(monkeypatch):
    def fake_get(url, headers=None):
        return DummyResponse()

    monkeypatch.setattr(requests, "get", fake_get)
    connector = MastodonConnector("http://host", "TOKEN")
    assert connector.is_connected()


def test_is_connected_error(monkeypatch):
    def fake_get(url, headers=None):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "get", fake_get)
    connector = MastodonConnector("http://host", "TOKEN")
    assert not connector.is_connected()
