import asyncio
import pytest

from app.handlers import openai_handler
from app.core.exceptions import APIError


def test_openai_handler_returns_fallback(monkeypatch):
    monkeypatch.setattr(openai_handler.settings, "openai_api_key", None, raising=False)

    messages = [{"role": "user", "content": "hi"}]
    resp = asyncio.run(openai_handler.create_chat_interaction(messages))
    assert resp.get("error") is True
    assert "Please add your OpenAI API key" in resp["choices"][0]["message"]["content"]


def test_openai_handler_raises_apierror(monkeypatch):
    monkeypatch.setattr(openai_handler.settings, "openai_api_key", "x", raising=False)

    class DummyCompletions:
        def create(self, *args, **kwargs):
            raise Exception("boom")

    class DummyChat:
        completions = DummyCompletions()

    class DummyClient:
        chat = DummyChat()

    monkeypatch.setattr(openai_handler, "_client", lambda: DummyClient())

    messages = [{"role": "user", "content": "hi"}]
    with pytest.raises(APIError):
        asyncio.run(openai_handler.create_chat_interaction(messages))
