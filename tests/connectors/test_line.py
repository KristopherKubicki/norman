import requests
import asyncio

from app.connectors.line_connector import LineConnector

class DummyResponse:
    def __init__(self, text="ok", status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("error")


def test_send_message_success(monkeypatch):
    def fake_post(url, json=None, headers=None):
        assert url == "https://api.line.me/v2/bot/message/push"
        assert json["to"] == "USER"
        assert json["messages"][0]["text"] == "hi"
        assert headers["Authorization"] == "Bearer TOKEN"
        return DummyResponse("sent")

    monkeypatch.setattr(requests, "post", fake_post)
    connector = LineConnector("TOKEN", "USER")
    assert connector.send_message("hi") == "sent"


def test_send_message_error(monkeypatch):
    def fake_post(url, json=None, headers=None):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "post", fake_post)
    connector = LineConnector("TOKEN", "USER")
    assert connector.send_message("hi") is None


def test_process_incoming():
    connector = LineConnector("TOKEN", "USER")
    payload = {"foo": "bar"}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == payload
