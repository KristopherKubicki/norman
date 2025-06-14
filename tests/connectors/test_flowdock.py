import asyncio
import httpx
from app.connectors.flowdock_connector import FlowdockConnector


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

    async def post(self, url, params=None, json=None):
        self.sent = (url, params, json)
        return self.response

    async def get(self, url, params=None, timeout=None):
        self.sent = (url, params)
        return self.response


def test_send_message_success(monkeypatch):
    resp = DummyResponse("sent")
    monkeypatch.setattr(httpx, "AsyncClient", lambda: DummyClient(resp))
    connector = FlowdockConnector("token", "flow")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"


def test_send_message_error(monkeypatch):
    class BadClient(DummyClient):
        async def post(self, url, params=None, json=None):
            raise httpx.HTTPError("fail")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: BadClient(DummyResponse()))
    connector = FlowdockConnector("token", "flow")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result is None


def test_is_connected(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: DummyResponse())
    connector = FlowdockConnector("token", "flow")
    assert connector.is_connected()


def test_is_connected_error(monkeypatch):
    def bad_get(*a, **kw):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "get", bad_get)
    connector = FlowdockConnector("token", "flow")
    assert not connector.is_connected()


def test_process_incoming():
    connector = FlowdockConnector("token", "flow")
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming({"msg": 1})
    )
    assert result == {"msg": 1}
