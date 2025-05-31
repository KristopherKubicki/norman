import requests
import asyncio

from app.connectors.viber_connector import ViberConnector

class DummyResponse:
    def __init__(self, text="ok", status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("error")


def test_send_message_success(monkeypatch):
    def fake_post(url, json=None, headers=None):
        assert url == "https://chatapi.viber.com/pa/send_message"
        assert json["receiver"] == "USER"
        assert json["text"] == "hi"
        assert headers["X-Viber-Auth-Token"] == "TOKEN"
        return DummyResponse("sent")

    monkeypatch.setattr(requests, "post", fake_post)
    connector = ViberConnector("TOKEN", "USER")
    assert connector.send_message("hi") == "sent"


def test_send_message_error(monkeypatch):
    def fake_post(url, json=None, headers=None):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "post", fake_post)
    connector = ViberConnector("TOKEN", "USER")
    assert connector.send_message("hi") is None


def test_process_incoming():
    connector = ViberConnector("TOKEN", "USER")
    payload = {"foo": "bar"}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == payload
