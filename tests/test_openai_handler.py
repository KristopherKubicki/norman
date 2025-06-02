import asyncio
import pytest

from app.handlers import openai_handler
from app.core.exceptions import APIError


def test_openai_handler_returns_fallback(monkeypatch):
    monkeypatch.setattr(openai_handler.openai, "api_key", None)

    async def _fail(*args, **kwargs):
        raise Exception("boom")

    monkeypatch.setattr(openai_handler.openai.ChatCompletion, "acreate", _fail)

    messages = [{"role": "user", "content": "hi"}]
    resp = asyncio.get_event_loop().run_until_complete(
        openai_handler.create_chat_interaction(messages)
    )
    assert resp.get("error") is True
    assert "Please add your OpenAI API key" in resp["choices"][0]["message"]["content"]


def test_openai_handler_raises_apierror(monkeypatch):
    monkeypatch.setattr(openai_handler.openai, "api_key", "x")

    async def _fail(*args, **kwargs):
        raise Exception("boom")

    monkeypatch.setattr(openai_handler.openai.ChatCompletion, "acreate", _fail)

    messages = [{"role": "user", "content": "hi"}]
    with pytest.raises(APIError):
        asyncio.get_event_loop().run_until_complete(
            openai_handler.create_chat_interaction(messages)
        )
