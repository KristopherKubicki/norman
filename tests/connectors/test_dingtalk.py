import asyncio
import httpx

from app.connectors.dingtalk_connector import DingTalkConnector


class DummyResponse:
    def __init__(self, text="ok", status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


class DummyClient:
    def __init__(self, response):
        self.response = response
        self.sent = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def post(self, url, json=None):
        self.sent = (url, json)
        return self.response


def test_send_message(monkeypatch):
    resp = DummyResponse("sent")
    monkeypatch.setattr(httpx, "AsyncClient", lambda: DummyClient(resp))
    connector = DingTalkConnector("token")
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message("hi")
    )
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_send_message_error(monkeypatch):
    class BadClient(DummyClient):
        async def post(self, url, json=None):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: BadClient(DummyResponse()))
    connector = DingTalkConnector("token")
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message("hi")
    )
    assert result is None


def test_process_incoming():
    connector = DingTalkConnector("token")
    payload = {"foo": "bar"}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == payload
