import asyncio
import httpx
from app.connectors.cap_connector import CAPConnector


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

    async def post(self, url, data=None):
        self.sent = (url, data)
        return self.response

    async def get(self, url):
        return self.response


def test_send_message_success(monkeypatch):
    resp = DummyResponse("sent")
    monkeypatch.setattr(httpx, "AsyncClient", lambda: DummyClient(resp))
    connector = CAPConnector("http://example.com")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_send_message_error(monkeypatch):
    class BadClient(DummyClient):
        async def post(self, url, data=None):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: BadClient(DummyResponse()))
    connector = CAPConnector("http://example.com")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result is None
    assert connector.sent_messages == []


def test_process_incoming():
    connector = CAPConnector("http://example.com")
    payload = {"foo": 1}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == payload


def test_listen_and_process(monkeypatch):
    xml = """
    <alert xmlns='urn:oasis:names:tc:emergency:cap:1.2'>
      <info>
        <headline>Test</headline>
        <description>Hello</description>
        <severity>Minor</severity>
      </info>
    </alert>
    """
    resp = DummyResponse(xml)
    monkeypatch.setattr(httpx, "AsyncClient", lambda: DummyClient(resp))
    connector = CAPConnector("http://example.com")
    result = asyncio.get_event_loop().run_until_complete(connector.listen_and_process())
    assert result == [{"headline": "Test", "description": "Hello", "severity": "Minor"}]


def test_listen_and_process_bad_xml(monkeypatch):
    resp = DummyResponse("<bad>")
    monkeypatch.setattr(httpx, "AsyncClient", lambda: DummyClient(resp))
    connector = CAPConnector("http://example.com")
    result = asyncio.get_event_loop().run_until_complete(connector.listen_and_process())
    assert result == []


class DummyGetResponse:
    def __init__(self, status=200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


def test_is_connected_success(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: DummyGetResponse())
    connector = CAPConnector("http://example.com")
    assert connector.is_connected()


def test_is_connected_error(monkeypatch):
    def raise_err(url, timeout=None):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "get", raise_err)
    connector = CAPConnector("http://example.com")
    assert not connector.is_connected()
