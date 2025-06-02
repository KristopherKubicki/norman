import asyncio
import httpx
from app.connectors.cap_connector import CAPConnector


def test_send_message():
    connector = CAPConnector("http://example.com")
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message({"msg": "hi"})
    )
    assert result == "sent"
    assert connector.sent_messages == [{"msg": "hi"}]


def test_process_incoming():
    connector = CAPConnector("http://example.com")
    payload = {"foo": 1}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == payload


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

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def post(self, url, data=None):
        return self.response

    async def get(self, url):
        return self.response


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
    result = asyncio.get_event_loop().run_until_complete(
        connector.listen_and_process()
    )
    assert result == [
        {"headline": "Test", "description": "Hello", "severity": "Minor"}
    ]
