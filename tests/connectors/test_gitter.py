import asyncio
import requests

from app.connectors.gitter_connector import GitterConnector


class DummyResponse:
    def __init__(self, text="ok", status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("error")


def test_send_message_success(monkeypatch):
    def fake_post(url, json=None, headers=None):
        return DummyResponse("sent")

    monkeypatch.setattr(requests, "post", fake_post)
    connector = GitterConnector("TOKEN", "ROOM")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"


def test_send_message_error(monkeypatch):
    def fake_post(url, json=None, headers=None):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "post", fake_post)
    connector = GitterConnector("TOKEN", "ROOM")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result is None


def test_process_incoming():
    connector = GitterConnector("TOKEN", "ROOM")
    payload = {"text": "hi"}
    result = asyncio.get_event_loop().run_until_complete(connector.process_incoming(payload))
    assert result == payload
