import requests
import asyncio

from app.connectors.telegram_connector import TelegramConnector


class DummyResponse:
    def __init__(self, text="ok", status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("error")


def test_send_message_success(monkeypatch):
    def fake_post(url, data=None, json=None):
        assert "sendMessage" in url
        return DummyResponse("sent")

    monkeypatch.setattr(requests, "post", fake_post)
    connector = TelegramConnector("TOKEN", "CHAT")
    assert connector.send_message("hi") == "sent"


def test_send_message_error(monkeypatch):
    def fake_post(url, data=None, json=None):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "post", fake_post)
    connector = TelegramConnector("TOKEN", "CHAT")
    assert connector.send_message("hi") is None


def test_process_incoming():
    connector = TelegramConnector("TOKEN", "CHAT")
    payload = {"message": {"text": "hello"}}
    assert connector.process_incoming(payload) == {
        "text": "hello",
        "channel": "Telegram",
    }


def test_set_webhook_success(monkeypatch):
    def fake_post(url, json=None):
        return DummyResponse("ok")

    monkeypatch.setattr(requests, "post", fake_post)
    connector = TelegramConnector("TOKEN", "CHAT")
    assert connector.set_webhook("http://example.com") is True


def test_set_webhook_error(monkeypatch):
    def fake_post(url, json=None):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "post", fake_post)
    connector = TelegramConnector("TOKEN", "CHAT")
    assert connector.set_webhook("http://example.com") is False


class DummyGetResponse:
    def __init__(self, ok=True):
        self._ok = ok

    def raise_for_status(self):
        if not self._ok:
            raise requests.HTTPError("error")

    def json(self):
        return {"ok": self._ok}


def test_is_connected_success(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url: DummyGetResponse(True))
    connector = TelegramConnector("TOKEN", "CHAT")
    assert connector.is_connected()


def test_is_connected_error(monkeypatch):
    def raise_err(url):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "get", raise_err)
    connector = TelegramConnector("TOKEN", "CHAT")
    assert not connector.is_connected()
