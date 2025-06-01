import asyncio
import openai
from app.handlers.openai_handler import create_chat_interaction


def test_create_chat_interaction_custom_params(monkeypatch):
    captured = {}

    def dummy_create(**kwargs):
        captured.update(kwargs)
        return {
            "model": kwargs.get("model"),
            "choices": [{"message": {"content": "hi"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr(openai.ChatCompletion, "create", dummy_create)

    messages = [{"role": "user", "content": "hi"}]
    result = asyncio.get_event_loop().run_until_complete(
        create_chat_interaction(
            messages,
            max_tokens=42,
            model="test-model",
            n=2,
            stop=["END"],
            temperature=0.5,
        )
    )

    assert captured["max_tokens"] == 42
    assert captured["n"] == 2
    assert captured["stop"] == ["END"]
    assert captured["temperature"] == 0.5
    assert result["choices"][0]["message"]["content"] == "hi"


def test_create_chat_interaction_missing_key(monkeypatch):
    def dummy_create(**kwargs):
        raise Exception("No API key provided")

    monkeypatch.setattr(openai.ChatCompletion, "create", dummy_create)
    openai.api_key = None
    messages = [{"role": "user", "content": "hello"}]
    result = asyncio.get_event_loop().run_until_complete(
        create_chat_interaction(messages)
    )
    assert result["error"] is True

