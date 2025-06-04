import asyncio
import httpx
from app.connectors.mastodon_connector import MastodonConnector


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

    async def post(self, url, headers=None, data=None):
        self.sent = (url, headers, data)
        return self.response


def test_send_message_success(monkeypatch):
    resp = DummyResponse("sent")
    monkeypatch.setattr(httpx, "AsyncClient", lambda: DummyClient(resp))
    connector = MastodonConnector("http://host", "TOKEN")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"


def test_send_message_error(monkeypatch):
    class BadClient(DummyClient):
        async def post(self, url, headers=None, data=None):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: BadClient(DummyResponse()))
    connector = MastodonConnector("http://host", "TOKEN")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result is None


class DummyGetResponse:
    def __init__(self, status=200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


def test_is_connected_success(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, headers=None: DummyGetResponse())
    connector = MastodonConnector("http://host", "TOKEN")
    assert connector.is_connected()


def test_is_connected_error(monkeypatch):
    def raise_err(url, headers=None):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "get", raise_err)
    connector = MastodonConnector("http://host", "TOKEN")
    assert not connector.is_connected()


class DummyStreamResponse:
    def __init__(self, lines):
        self.lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for line in self.lines:
            yield line


class StreamClient(DummyClient):
    def __init__(self, response):
        super().__init__(response)

    def stream(self, method, url, headers=None, params=None):
        self.sent_stream = (method, url, headers, params)
        return self.response


def test_listen_and_process(monkeypatch):
    lines = [
        "event: update",
        'data: {"content": "hi"}',
        "",
    ]
    resp = DummyStreamResponse(lines)
    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout=None: StreamClient(resp))

    processed = []

    class TestConnector(MastodonConnector):
        async def process_incoming(self, message):
            processed.append(await super().process_incoming(message))

    connector = TestConnector("http://host", "TOKEN")
    asyncio.get_event_loop().run_until_complete(connector.listen_and_process())
    assert processed == [{"event": "update", "data": {"content": "hi"}}]


def test_listen_and_process_error(monkeypatch):
    class BadClient(StreamClient):
        def stream(self, method, url, headers=None, params=None):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout=None: BadClient(DummyStreamResponse([])))

    connector = MastodonConnector("http://host", "TOKEN")
    result = asyncio.get_event_loop().run_until_complete(connector.listen_and_process())
    assert result is None
