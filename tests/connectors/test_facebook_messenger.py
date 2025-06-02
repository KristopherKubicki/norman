import asyncio
import httpx

from app.connectors.facebook_messenger_connector import FacebookMessengerConnector


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


def test_send_message_success(monkeypatch):
    resp = DummyResponse("sent")
    client = DummyClient(resp)
    monkeypatch.setattr(httpx, "AsyncClient", lambda: client)
    connector = FacebookMessengerConnector("TOKEN", "VERIFY")
    msg = {"message": {"text": "hi"}, "recipient": {"id": "U"}}
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message(msg)
    )
    assert result == "sent"
    assert client.sent[0].startswith("https://graph.facebook.com")


def test_send_message_error(monkeypatch):
    class BadClient(DummyClient):
        async def post(self, url, params=None, json=None):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: BadClient(DummyResponse()))
    connector = FacebookMessengerConnector("TOKEN", "VERIFY")
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message({"message": {"text": "hi"}})
    )
    assert result is None


def test_process_incoming():
    connector = FacebookMessengerConnector("TOKEN", "VERIFY")
    payload = {"foo": 1}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == payload


def test_listen_and_process():
    connector = FacebookMessengerConnector("TOKEN", "VERIFY")
    result = asyncio.get_event_loop().run_until_complete(
        connector.listen_and_process()
    )
    assert result is None
