import requests
import asyncio

from app.connectors.zulip_connector import ZulipConnector


class DummyResponse:
    def __init__(self, text="ok", status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("error")


def test_send_message_success(monkeypatch):
    def fake_post(url, data=None, auth=None):
        assert "api/v1/messages" in url
        assert data["content"] == "hi"
        return DummyResponse("sent")

    monkeypatch.setattr(requests, "post", fake_post)
    connector = ZulipConnector("email", "KEY", "https://zulip.example.com", "stream", "topic")
    assert connector.send_message("hi") == "sent"


def test_send_message_error(monkeypatch):
    def fake_post(url, data=None, auth=None):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "post", fake_post)
    connector = ZulipConnector("email", "KEY", "https://zulip.example.com", "stream", "topic")
    assert connector.send_message("hi") is None


def test_process_incoming():
    connector = ZulipConnector("email", "KEY", "https://zulip.example.com", "stream", "topic")
    payload = {"foo": "bar"}
    result = asyncio.get_event_loop().run_until_complete(connector.process_incoming(payload))
    assert result == payload


def test_is_connected_success(monkeypatch):
    def fake_get(url, auth=None):
        return DummyResponse(status=200)

    monkeypatch.setattr(requests, "get", fake_get)
    connector = ZulipConnector("email", "KEY", "https://zulip.example.com", "stream", "topic")
    assert connector.is_connected()


def test_is_connected_error(monkeypatch):
    def fake_get(url, auth=None):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "get", fake_get)
    connector = ZulipConnector("email", "KEY", "https://zulip.example.com", "stream", "topic")
    assert not connector.is_connected()
