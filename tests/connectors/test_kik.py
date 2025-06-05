import asyncio
import httpx

from app.connectors.kik_connector import KikConnector


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

    async def post(self, url, json=None, auth=None):
        self.sent = (url, json, auth)
        return self.response


def test_send_message_success(monkeypatch):
    resp = DummyResponse("sent")
    client = DummyClient(resp)
    monkeypatch.setattr(httpx, "AsyncClient", lambda: client)
    connector = KikConnector("user", "key")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"
    assert client.sent[0].endswith("/message")


def test_send_message_error(monkeypatch):
    class BadClient(DummyClient):
        async def post(self, url, json=None, auth=None):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: BadClient(DummyResponse()))
    connector = KikConnector("user", "key")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result is None


def test_process_incoming():
    connector = KikConnector("user", "key")
    payload = {"body": "hello", "from": "alice", "id": "1"}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == {"text": "hello", "from": "alice", "id": "1"}


class DummyGetResponse:
    def __init__(self, status=200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


def test_is_connected_success(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, auth=None: DummyGetResponse())
    connector = KikConnector("user", "key")
    assert connector.is_connected()


def test_is_connected_error(monkeypatch):
    def raise_err(url, auth=None):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "get", raise_err)
    connector = KikConnector("user", "key")
    assert not connector.is_connected()
