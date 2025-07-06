import asyncio
import httpx
from app.connectors.sms_connector import SMSConnector


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
    connector = SMSConnector(
        account_sid="SID",
        auth_token="TOKEN",
        from_number="+1",
        to_number="+2",
    )
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message("hello")
    )
    assert result == "sent"


def test_send_message_error(monkeypatch):
    class BadClient(DummyClient):
        async def post(self, url, data=None, auth=None):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: BadClient(DummyResponse()))
    connector = SMSConnector(
        account_sid="SID",
        auth_token="TOKEN",
        from_number="+1",
        to_number="+2",
    )
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message("hello")
    )
    assert result is None
