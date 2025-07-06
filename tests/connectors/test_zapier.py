import asyncio
import httpx
from app.connectors.zapier_connector import ZapierConnector


class DummyResponse:
    def __init__(self, text="ok", status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


class DummyClient:
    def __init__(self, resp):
        self.resp = resp
        self.sent = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def post(self, url, json=None):
        self.sent = (url, json)
        return self.resp


def test_send_message_success(monkeypatch):
    resp = DummyResponse("sent")
    monkeypatch.setattr(httpx, "AsyncClient", lambda: DummyClient(resp))
    connector = ZapierConnector("http://hook")
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message({"a": 1})
    )
    assert result == "sent"


def test_send_message_error(monkeypatch):
    class BadClient(DummyClient):
        async def post(self, url, json=None):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: BadClient(DummyResponse()))
    connector = ZapierConnector("http://hook")
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message({"a": 1})
    )
    assert result is None
