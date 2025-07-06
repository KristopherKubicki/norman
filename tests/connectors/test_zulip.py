import asyncio
import httpx
from app.connectors.zulip_connector import ZulipConnector


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

    async def post(self, url, data=None, auth=None):
        self.sent = (url, data, auth)
        return self.response


def test_send_message_success(monkeypatch):
    resp = DummyResponse("sent")
    monkeypatch.setattr(httpx, "AsyncClient", lambda: DummyClient(resp))
    connector = ZulipConnector(
        "email", "KEY", "https://zulip.example.com", "stream", "topic"
    )
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"


def test_send_message_error(monkeypatch):
    class BadClient(DummyClient):
        async def post(self, url, data=None, auth=None):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: BadClient(DummyResponse()))
    connector = ZulipConnector(
        "email", "KEY", "https://zulip.example.com", "stream", "topic"
    )
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result is None


def test_process_incoming():
    connector = ZulipConnector(
        "email", "KEY", "https://zulip.example.com", "stream", "topic"
    )
    payload = {"foo": "bar"}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == payload


def test_is_connected_success(monkeypatch):
    def fake_get(url, auth=None):
        return DummyResponse(status=200)

    monkeypatch.setattr(httpx, "get", fake_get)
    connector = ZulipConnector(
        "email", "KEY", "https://zulip.example.com", "stream", "topic"
    )
    assert connector.is_connected()


def test_is_connected_error(monkeypatch):
    def fake_get(url, auth=None):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "get", fake_get)
    connector = ZulipConnector(
        "email", "KEY", "https://zulip.example.com", "stream", "topic"
    )
    assert not connector.is_connected()
