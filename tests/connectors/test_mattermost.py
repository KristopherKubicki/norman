import asyncio
import httpx
from app.connectors.mattermost_connector import MattermostConnector


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

    async def post(self, url, json=None, headers=None):
        self.sent = (url, json, headers)
        return self.response


def test_send_message(monkeypatch):
    resp = DummyResponse("sent")
    monkeypatch.setattr(httpx, "AsyncClient", lambda: DummyClient(resp))
    connector = MattermostConnector("http://mm", "tok", "chan")
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message("hi")
    )
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_send_message_error(monkeypatch):
    class BadClient(DummyClient):
        async def post(self, url, json=None, headers=None):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: BadClient(DummyResponse()))
    connector = MattermostConnector("http://mm", "tok", "chan")
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message("hi")
    )
    assert result is None


def test_process_incoming():
    connector = MattermostConnector("http://mm", "tok", "chan")
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming({"foo": "bar"})
    )
    assert result == {"foo": "bar"}


class DummyGetResponse:
    def __init__(self, status=200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


def test_is_connected_success(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, headers=None: DummyGetResponse())
    connector = MattermostConnector("http://mm", "tok", "chan")
    assert connector.is_connected()


def test_is_connected_error(monkeypatch):
    def raise_err(url, headers=None):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "get", raise_err)
    connector = MattermostConnector("http://mm", "tok", "chan")
    assert not connector.is_connected()
