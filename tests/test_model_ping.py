import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import model_ping


def _disable_provider_chain(monkeypatch):
    monkeypatch.setattr(model_ping.settings, "openai_api_key", "", raising=False)
    monkeypatch.setattr(
        model_ping.settings, "openai_default_model", "gpt-test", raising=False
    )
    monkeypatch.setattr(
        model_ping.settings, "llm_primary_provider", "openai", raising=False
    )
    monkeypatch.setattr(model_ping.settings, "llm_primary_api_key", "", raising=False)
    monkeypatch.setattr(model_ping.settings, "llm_primary_base_url", "", raising=False)
    monkeypatch.setattr(model_ping.settings, "llm_primary_model", "", raising=False)
    monkeypatch.setattr(
        model_ping.settings, "llm_backup_provider", "disabled", raising=False
    )
    monkeypatch.setattr(model_ping.settings, "llm_backup_api_key", "", raising=False)
    monkeypatch.setattr(model_ping.settings, "llm_backup_base_url", "", raising=False)
    monkeypatch.setattr(model_ping.settings, "llm_backup_model", "", raising=False)
    monkeypatch.setattr(
        model_ping.settings, "llm_offline_provider", "disabled", raising=False
    )
    monkeypatch.setattr(model_ping.settings, "llm_offline_api_key", "", raising=False)
    monkeypatch.setattr(model_ping.settings, "llm_offline_base_url", "", raising=False)
    monkeypatch.setattr(model_ping.settings, "llm_offline_model", "", raising=False)
    monkeypatch.setattr(model_ping.settings, "llm_ping_targets", [], raising=False)


def test_model_ping_targets_merge_provider_chain_and_custom_targets(monkeypatch):
    monkeypatch.setattr(
        model_ping.settings, "openai_api_key", "openai-key", raising=False
    )
    monkeypatch.setattr(
        model_ping.settings, "openai_default_model", "gpt-5.5", raising=False
    )
    monkeypatch.setattr(
        model_ping.settings, "llm_primary_provider", "openai", raising=False
    )
    monkeypatch.setattr(model_ping.settings, "llm_primary_api_key", "", raising=False)
    monkeypatch.setattr(model_ping.settings, "llm_primary_base_url", "", raising=False)
    monkeypatch.setattr(model_ping.settings, "llm_primary_model", "", raising=False)
    monkeypatch.setattr(
        model_ping.settings, "llm_backup_provider", "openai_compatible", raising=False
    )
    monkeypatch.setattr(
        model_ping.settings,
        "llm_backup_base_url",
        "https://user:pass@llm.knox.lollie.org/v1?secret=x",
        raising=False,
    )
    monkeypatch.setattr(
        model_ping.settings, "llm_backup_model", "qwen3:8b", raising=False
    )
    monkeypatch.setattr(
        model_ping.settings, "llm_offline_provider", "disabled", raising=False
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setattr(
        model_ping.settings,
        "llm_ping_targets",
        [
            {
                "id": "claude-main",
                "name": "Claude main",
                "provider": "anthropic",
                "model": "claude-sonnet-test",
                "api_key_env": "ANTHROPIC_API_KEY",
            }
        ],
        raising=False,
    )

    targets = model_ping.list_model_ping_targets()

    assert [item["id"] for item in targets] == [
        "provider-primary",
        "provider-backup",
        "claude-main",
    ]
    assert all("api_key" not in item for item in targets)
    assert targets[0]["configured"] is True
    assert targets[1]["base_url"] == "https://llm.knox.lollie.org/v1"
    assert targets[2]["configured"] is True


def test_ping_model_targets_runs_selected_openai_compatible_target(monkeypatch):
    _disable_provider_chain(monkeypatch)
    monkeypatch.setattr(
        model_ping.settings,
        "llm_ping_targets",
        [
            {
                "id": "local-qwen",
                "name": "Local Qwen",
                "provider": "openai_compatible",
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "qwen3:8b",
            }
        ],
        raising=False,
    )
    monkeypatch.setattr(
        model_ping,
        "_ping_openai_chat",
        lambda target: model_ping.EXPECTED_PING_TEXT,
    )

    payload = asyncio.run(model_ping.ping_model_targets(target_id="local-qwen"))

    assert payload["count"] == 1
    assert payload["ok"] == 1
    assert payload["items"][0]["status"] == "ok"
    assert payload["items"][0]["matched"] is True
    assert payload["items"][0]["base_url"] == "http://127.0.0.1:11434/v1"


def test_ping_model_targets_runs_selected_norllama_target(monkeypatch):
    _disable_provider_chain(monkeypatch)
    monkeypatch.setattr(
        model_ping.settings,
        "llm_ping_targets",
        [
            {
                "id": "norllama-qwen",
                "name": "Norllama Qwen",
                "provider": "norllama",
                "base_url": "http://127.0.0.1:11434",
                "model": "qwen3:8b",
            }
        ],
        raising=False,
    )
    monkeypatch.setattr(
        model_ping,
        "_ping_norllama",
        lambda target: model_ping.EXPECTED_PING_TEXT,
    )

    targets = model_ping.list_model_ping_targets()
    payload = asyncio.run(model_ping.ping_model_targets(target_id="norllama-qwen"))

    assert targets[0]["configured"] is True
    assert payload["count"] == 1
    assert payload["ok"] == 1
    assert payload["items"][0]["provider"] == "norllama"


def test_ping_model_targets_reports_missing_target(monkeypatch):
    _disable_provider_chain(monkeypatch)

    with pytest.raises(KeyError):
        asyncio.run(model_ping.ping_model_targets(target_id="missing"))


def test_ping_openai_compatible_home_arpa_uses_system_tls_bundle(monkeypatch):
    target = model_ping.ModelPingTarget(
        id="local-qwen",
        name="Local Qwen",
        provider="openai_compatible",
        base_url="https://llm.home.arpa/v1",
        model="qwen3:8b",
        timeout_seconds=7.5,
    )
    system_context = object()
    http_client = Mock()
    client_factory = Mock(return_value=http_client)
    openai_client = Mock(
        return_value=SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=Mock(
                        return_value=SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    message=SimpleNamespace(
                                        content=model_ping.EXPECTED_PING_TEXT
                                    )
                                )
                            ]
                        )
                    )
                )
            )
        )
    )
    monkeypatch.setattr(
        model_ping.ssl, "create_default_context", lambda: system_context
    )
    monkeypatch.setattr(model_ping.httpx, "Client", client_factory)
    monkeypatch.setattr(model_ping, "_openai_client", openai_client)

    response = model_ping._ping_openai_chat(target)

    assert response == model_ping.EXPECTED_PING_TEXT
    client_factory.assert_called_once_with(verify=system_context, timeout=7.5)
    openai_client.assert_called_once_with(target, http_client=http_client)
    http_client.close.assert_called_once_with()
