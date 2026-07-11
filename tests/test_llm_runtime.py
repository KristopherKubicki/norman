from app.core.config import settings
from app.services.llm_runtime import (
    get_llm_runtime_status,
    record_llm_failure,
    record_llm_success,
    reset_llm_runtime_state,
)


def test_llm_runtime_status_defaults_to_primary_when_openai_configured(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-openai", raising=False)
    monkeypatch.setattr(settings, "llm_primary_provider", "openai", raising=False)
    monkeypatch.setattr(settings, "llm_primary_api_key", "", raising=False)
    monkeypatch.setattr(settings, "llm_primary_model", "gpt-5-mini", raising=False)
    monkeypatch.setattr(settings, "llm_backup_provider", "disabled", raising=False)
    monkeypatch.setattr(settings, "llm_offline_provider", "disabled", raising=False)
    reset_llm_runtime_state()

    status = get_llm_runtime_status()
    assert status["configured"] is True
    assert status["mode"] == "primary"
    assert status["providers"][0]["configured"] is True


def test_llm_runtime_records_backup_failover(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-openai", raising=False)
    monkeypatch.setattr(settings, "llm_primary_provider", "openai", raising=False)
    monkeypatch.setattr(
        settings, "llm_backup_provider", "openai_compatible", raising=False
    )
    monkeypatch.setattr(
        settings, "llm_backup_base_url", "http://127.0.0.1:11434/v1", raising=False
    )
    reset_llm_runtime_state()

    record_llm_success(
        provider_slot="backup",
        provider_kind="openai_compatible",
        active_model="qwen3:latest",
        fallback_reason="primary unavailable",
        provider_label="Backup",
    )

    status = get_llm_runtime_status()
    assert status["mode"] == "backup_online"
    assert status["fallback_active"] is True
    assert status["fallback_reason"] == "primary unavailable"
    assert status["active_model"] == "qwen3:latest"


def test_llm_runtime_records_control_only_failure(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "", raising=False)
    monkeypatch.setattr(settings, "llm_primary_provider", "openai", raising=False)
    monkeypatch.setattr(settings, "llm_backup_provider", "disabled", raising=False)
    monkeypatch.setattr(settings, "llm_offline_provider", "disabled", raising=False)
    reset_llm_runtime_state()

    record_llm_failure(last_error="all providers unavailable", primary_error="boom")

    status = get_llm_runtime_status()
    assert status["mode"] == "control_only"
    assert status["last_error"] == "all providers unavailable"
    assert status["last_primary_error"] == "boom"


def test_llm_runtime_labels_norllama_provider(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "", raising=False)
    monkeypatch.setattr(settings, "llm_primary_provider", "openai", raising=False)
    monkeypatch.setattr(settings, "llm_backup_provider", "disabled", raising=False)
    monkeypatch.setattr(settings, "llm_offline_provider", "norllama", raising=False)
    monkeypatch.setattr(
        settings, "llm_offline_base_url", "http://127.0.0.1:11434", raising=False
    )
    reset_llm_runtime_state()

    status = get_llm_runtime_status()

    assert status["providers"][2]["label"] == "Norllama"
