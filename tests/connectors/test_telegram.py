import asyncio
import httpx
from app.connectors.telegram_connector import TelegramConnector


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

    async def post(self, url, data=None, json=None):
        self.sent = (url, data, json)
        return self.response


def test_send_message_success(monkeypatch):
    resp = DummyResponse("sent")
    monkeypatch.setattr(httpx, "AsyncClient", lambda: DummyClient(resp))
    connector = TelegramConnector("TOKEN", "CHAT")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"


def test_send_message_error(monkeypatch):
    class BadClient(DummyClient):
        async def post(self, url, data=None, json=None):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: BadClient(DummyResponse()))
    connector = TelegramConnector("TOKEN", "CHAT")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result is None


def test_process_incoming():
    connector = TelegramConnector("TOKEN", "CHAT")
    payload = {"message": {"text": "hello"}}
    assert connector.process_incoming(payload) == {
        "text": "hello",
        "channel": "Telegram",
    }


def test_set_webhook_success(monkeypatch):
    resp = DummyResponse("ok")
    monkeypatch.setattr(httpx, "AsyncClient", lambda: DummyClient(resp))
    connector = TelegramConnector("TOKEN", "CHAT")
    result = asyncio.get_event_loop().run_until_complete(
        connector.set_webhook("http://example.com")
    )
    assert result is True


def test_set_webhook_error(monkeypatch):
    class BadClient(DummyClient):
        async def post(self, url, json=None):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: BadClient(DummyResponse()))
    connector = TelegramConnector("TOKEN", "CHAT")
    result = asyncio.get_event_loop().run_until_complete(
        connector.set_webhook("http://example.com")
    )
    assert result is False


class DummyGetResponse:
    def __init__(self, ok=True):
        self._ok = ok

    def raise_for_status(self):
        if not self._ok:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self):
        return {"ok": self._ok}


def test_is_connected_success(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url: DummyGetResponse(True))
    connector = TelegramConnector("TOKEN", "CHAT")
    assert connector.is_connected()


def test_is_connected_error(monkeypatch):
    def raise_err(url):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "get", raise_err)
    connector = TelegramConnector("TOKEN", "CHAT")
    assert not connector.is_connected()


class DummyUpdateResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_listen_and_process(monkeypatch):
    resp = DummyUpdateResponse({"ok": True, "result": [{"update_id": 1, "message": {"text": "hi"}}]})

    class Client(DummyClient):
        async def get(self, url, params=None, timeout=None):
            self.sent_get = (url, params)
            return resp

    monkeypatch.setattr(httpx, "AsyncClient", lambda: Client(resp))

    connector = TelegramConnector("TOKEN", "CHAT")
    results = asyncio.get_event_loop().run_until_complete(
        connector.listen_and_process()
    )
    assert results == [{"text": "hi", "channel": "Telegram"}]


def test_listen_and_process_error(monkeypatch):
    class BadClient(DummyClient):
        async def get(self, url, params=None, timeout=None):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: BadClient(DummyResponse()))
    connector = TelegramConnector("TOKEN", "CHAT")
    results = asyncio.get_event_loop().run_until_complete(
        connector.listen_and_process()
    )
    assert results == []
