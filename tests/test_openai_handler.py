import asyncio
import pytest

from app.handlers import openai_handler
from app.core.exceptions import APIError


def test_openai_handler_returns_fallback(monkeypatch):
    monkeypatch.setattr(openai_handler.settings, "openai_api_key", None, raising=False)
    monkeypatch.setattr(
        openai_handler.settings, "llm_primary_provider", "openai", raising=False
    )
    monkeypatch.setattr(
        openai_handler.settings, "llm_backup_provider", "disabled", raising=False
    )
    monkeypatch.setattr(
        openai_handler.settings, "llm_offline_provider", "disabled", raising=False
    )

    messages = [{"role": "user", "content": "hi"}]
    resp = asyncio.run(openai_handler.create_chat_interaction(messages))
    assert resp.get("error") is True
    assert (
        "Please configure a primary, backup, or offline LLM provider"
        in resp["choices"][0]["message"]["content"]
    )


def test_openai_handler_raises_apierror(monkeypatch):
    monkeypatch.setattr(openai_handler.settings, "openai_api_key", "x", raising=False)
    monkeypatch.setattr(
        openai_handler.settings, "llm_primary_provider", "openai", raising=False
    )
    monkeypatch.setattr(
        openai_handler.settings, "llm_backup_provider", "disabled", raising=False
    )
    monkeypatch.setattr(
        openai_handler.settings, "llm_offline_provider", "disabled", raising=False
    )

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


def test_openai_handler_falls_back_to_backup_provider(monkeypatch):
    monkeypatch.setattr(openai_handler.settings, "openai_api_key", "x", raising=False)
    monkeypatch.setattr(
        openai_handler.settings, "llm_primary_provider", "openai", raising=False
    )
    monkeypatch.setattr(
        openai_handler.settings,
        "llm_backup_provider",
        "openai_compatible",
        raising=False,
    )
    monkeypatch.setattr(
        openai_handler.settings,
        "llm_backup_base_url",
        "http://127.0.0.1:11434/v1",
        raising=False,
    )
    monkeypatch.setattr(
        openai_handler.settings, "llm_backup_model", "qwen3:latest", raising=False
    )
    monkeypatch.setattr(
        openai_handler.settings, "llm_offline_provider", "disabled", raising=False
    )

    class DummyUsage:
        prompt_tokens = 11
        completion_tokens = 7

    class DummyResponse:
        model = "qwen3:latest"
        choices = [
            type(
                "Choice", (), {"message": type("Msg", (), {"content": "backup ok"})()}
            )()
        ]
        usage = DummyUsage()

    class PrimaryCompletions:
        def create(self, *args, **kwargs):
            raise Exception("primary boom")

    class BackupCompletions:
        def create(self, *args, **kwargs):
            return DummyResponse()

    class PrimaryClient:
        chat = type("Chat", (), {"completions": PrimaryCompletions()})()

    class BackupClient:
        chat = type("Chat", (), {"completions": BackupCompletions()})()

    monkeypatch.setattr(openai_handler, "_client", lambda: PrimaryClient())
    monkeypatch.setattr(
        openai_handler,
        "_provider_client",
        lambda attempt: BackupClient() if attempt.slot == "backup" else PrimaryClient(),
    )

    messages = [{"role": "user", "content": "hi"}]
    resp = asyncio.run(openai_handler.create_chat_interaction(messages))
    assert resp["choices"][0]["message"]["content"] == "backup ok"
    assert resp["headers"]["llm_provider"] == "backup"
    assert resp["headers"]["llm_mode"] == "backup_online"
    assert resp["headers"]["llm_fallback_reason"] == "primary boom"


def test_openai_handler_uses_offline_provider(monkeypatch):
    monkeypatch.setattr(openai_handler.settings, "openai_api_key", "", raising=False)
    monkeypatch.setattr(
        openai_handler.settings, "llm_primary_provider", "openai", raising=False
    )
    monkeypatch.setattr(
        openai_handler.settings, "llm_backup_provider", "disabled", raising=False
    )
    monkeypatch.setattr(
        openai_handler.settings,
        "llm_offline_provider",
        "openai_compatible",
        raising=False,
    )
    monkeypatch.setattr(
        openai_handler.settings,
        "llm_offline_base_url",
        "https://llm.knox.lollie.org/v1",
        raising=False,
    )
    monkeypatch.setattr(
        openai_handler.settings, "llm_offline_model", "qwen3:8b", raising=False
    )

    class DummyUsage:
        prompt_tokens = 5
        completion_tokens = 9

    class DummyResponse:
        model = "qwen3:8b"
        choices = [
            type(
                "Choice", (), {"message": type("Msg", (), {"content": "offline ok"})()}
            )()
        ]
        usage = DummyUsage()

    class OfflineCompletions:
        def create(self, *args, **kwargs):
            return DummyResponse()

    class OfflineClient:
        chat = type("Chat", (), {"completions": OfflineCompletions()})()

    monkeypatch.setattr(
        openai_handler, "_provider_client", lambda attempt: OfflineClient()
    )

    messages = [{"role": "user", "content": "hi"}]
    resp = asyncio.run(openai_handler.create_chat_interaction(messages))
    assert resp["choices"][0]["message"]["content"] == "offline ok"
    assert resp["headers"]["llm_provider"] == "offline"
    assert resp["headers"]["llm_mode"] == "offline_local"


def test_openai_handler_routes_to_native_norllama_provider(monkeypatch):
    monkeypatch.setattr(openai_handler.settings, "openai_api_key", "", raising=False)
    monkeypatch.setattr(
        openai_handler.settings, "llm_primary_provider", "openai", raising=False
    )
    monkeypatch.setattr(
        openai_handler.settings, "llm_backup_provider", "disabled", raising=False
    )
    monkeypatch.setattr(
        openai_handler.settings, "llm_offline_provider", "norllama", raising=False
    )
    monkeypatch.setattr(
        openai_handler.settings,
        "llm_offline_base_url",
        "http://127.0.0.1:11434",
        raising=False,
    )
    monkeypatch.setattr(
        openai_handler.settings,
        "llm_offline_model",
        "qwen3:8b",
        raising=False,
    )
    calls = []

    def fake_invoke_text_chat(**kwargs):
        calls.append(kwargs)
        return {
            "model": kwargs["model"],
            "choices": [{"message": {"content": "norllama ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            "headers": {},
        }

    monkeypatch.setattr(
        openai_handler.norllama_gateway,
        "invoke_text_chat",
        fake_invoke_text_chat,
    )

    messages = [{"role": "user", "content": "hi"}]
    resp = asyncio.run(openai_handler.create_chat_interaction(messages))

    assert resp["choices"][0]["message"]["content"] == "norllama ok"
    assert resp["headers"]["llm_provider"] == "offline"
    assert resp["headers"]["llm_provider_kind"] == "norllama"
    assert resp["headers"]["llm_mode"] == "offline_local"
    assert calls[0]["base_url"] == "http://127.0.0.1:11434"
