# tests/test_webhook.py
"""Tests for the simple webhook connector."""

import asyncio

import httpx
from app.connectors.webhook_connector import (
    WebhookConnector,
    IncomingMessage,
    process_webhook_message,
)


class DummyResponse:
    def __init__(self, text: str = "ok", status: int = 200):
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


class DummyClient:
    def __init__(self, response: DummyResponse):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def post(self, url, json=None):
        return self.response


def test_process_webhook_message(monkeypatch) -> None:
    resp = DummyResponse("sent")
    monkeypatch.setattr(httpx, "AsyncClient", lambda: DummyClient(resp))
    msg = IncomingMessage(channel="c1", message="hi", user="u1")
    result = asyncio.get_event_loop().run_until_complete(process_webhook_message(msg))
    assert result == "sent"

