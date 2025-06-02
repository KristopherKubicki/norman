import asyncio
import httpx
from app.connectors.bluesky_connector import BlueskyConnector


class DummyResponse:
    def __init__(self, json_data=None, text="ok", status=200):
        self._json = json_data or {}
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self):
        return self._json


class DummyClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.idx = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def post(self, url, json=None, headers=None):
        self.calls.append((url, json, headers))
        resp = self.responses[self.idx]
        self.idx += 1
        return resp


def test_send_message_success(monkeypatch):
    login_resp = DummyResponse({"accessJwt": "tok"})
    send_resp = DummyResponse(text="sent")
    client = DummyClient([login_resp, send_resp])
    monkeypatch.setattr(httpx, "AsyncClient", lambda: client)
    connector = BlueskyConnector("h", "pw")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"
    assert connector.sent_messages == ["hi"]
    assert client.calls[0][0].endswith("/com.atproto.server.createSession")
    assert client.calls[1][0].endswith("/com.atproto.repo.createRecord")


def test_send_message_error(monkeypatch):
    class BadClient(DummyClient):
        async def post(self, url, json=None, headers=None):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: BadClient([]))
    connector = BlueskyConnector("h", "pw")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result is None
    assert connector.sent_messages == []


def test_process_incoming():
    connector = BlueskyConnector("h", "pw")
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming({"x": 1})
    )
    assert result == {"x": 1}
