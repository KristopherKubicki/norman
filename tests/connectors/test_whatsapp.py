import asyncio
import httpx
from app.connectors.whatsapp_connector import WhatsAppConnector


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
    connector = WhatsAppConnector("SID", "TOKEN", "+1", "+2")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"


def test_send_message_error(monkeypatch):
    class BadClient(DummyClient):
        async def post(self, url, data=None, auth=None):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: BadClient(DummyResponse()))
    connector = WhatsAppConnector("SID", "TOKEN", "+1", "+2")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result is None


def test_process_incoming():
    connector = WhatsAppConnector("SID", "TOKEN", "+1", "+2")
    payload = {"body": "hello", "from": "+2", "sid": "123"}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == {
        "text": "hello",
        "from": "+2",
        "to": "+2",
        "sid": "123",
    }


def test_is_connected_success(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, auth=None: DummyResponse())
    connector = WhatsAppConnector("SID", "TOKEN", "+1", "+2")
    assert connector.is_connected()


def test_is_connected_error(monkeypatch):
    def raise_err(url, auth=None):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "get", raise_err)
    connector = WhatsAppConnector("SID", "TOKEN", "+1", "+2")
    assert not connector.is_connected()
