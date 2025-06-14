import asyncio
import httpx
from app.connectors.jira_service_desk_connector import JiraServiceDeskConnector


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


def test_send_message_issue(monkeypatch):
    resp = DummyResponse("sent")
    monkeypatch.setattr(httpx, "AsyncClient", lambda: DummyClient(resp))
    connector = JiraServiceDeskConnector("http://s", "e", "t", "PROJ")
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message({"summary": "hi"})
    )
    assert result == "sent"


def test_send_message_error(monkeypatch):
    class BadClient(DummyClient):
        async def post(self, url, json=None, headers=None):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: BadClient(DummyResponse()))
    connector = JiraServiceDeskConnector("http://s", "e", "t", "PROJ")
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message({"summary": "hi"})
    )
    assert result is None
