from app.services import llm_runtime


class DummyResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def json(self):
        return self._payload


def _disable_all(monkeypatch):
    settings = llm_runtime.settings
    monkeypatch.setattr(settings, "llm_primary_provider", "disabled")
    monkeypatch.setattr(settings, "llm_primary_api_key", "")
    monkeypatch.setattr(settings, "llm_primary_base_url", "")
    monkeypatch.setattr(settings, "llm_primary_model", "")
    monkeypatch.setattr(settings, "llm_backup_provider", "disabled")
    monkeypatch.setattr(settings, "llm_backup_api_key", "")
    monkeypatch.setattr(settings, "llm_backup_base_url", "")
    monkeypatch.setattr(settings, "llm_backup_model", "")
    monkeypatch.setattr(settings, "llm_offline_provider", "disabled")
    monkeypatch.setattr(settings, "llm_offline_api_key", "")
    monkeypatch.setattr(settings, "llm_offline_base_url", "")
    monkeypatch.setattr(settings, "llm_offline_model", "")


def test_llm_runtime_reports_primary_openai_when_key_configured(monkeypatch):
    _disable_all(monkeypatch)
    monkeypatch.setattr(llm_runtime.settings, "openai_default_model", "gpt-5.5")
    monkeypatch.setattr(llm_runtime.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(llm_runtime.settings, "llm_primary_provider", "openai")

    status = llm_runtime.get_llm_runtime_status()

    assert status["mode"] == "primary"
    assert status["active_provider_label"] == "OpenAI"
    assert status["active_model"] == "gpt-5.5"


def test_llm_runtime_falls_back_to_local_ollama(monkeypatch):
    _disable_all(monkeypatch)
    monkeypatch.setattr(llm_runtime.settings, "openai_api_key", "")
    monkeypatch.setattr(llm_runtime.settings, "llm_primary_provider", "openai")
    monkeypatch.setattr(llm_runtime.settings, "llm_offline_provider", "ollama")
    monkeypatch.setattr(
        llm_runtime.settings, "llm_offline_base_url", "http://192.168.0.133:11434"
    )
    monkeypatch.setattr(llm_runtime.settings, "llm_offline_model", "qwen3:8b")
    monkeypatch.setattr(llm_runtime.settings, "llm_provider_timeout_seconds", 45)

    def fake_get(url, headers=None, timeout=None):
        assert url == "http://192.168.0.133:11434/api/tags"
        return DummyResponse({"models": [{"name": "qwen3:8b"}]})

    monkeypatch.setattr(llm_runtime.requests, "get", fake_get)

    status = llm_runtime.get_llm_runtime_status()

    assert status["mode"] == "offline_local"
    assert status["mode_label"] == "Offline"
    assert status["active_provider_label"] == "Ollama"
    assert status["active_model"] == "qwen3:8b"
    assert "API key missing" in status["fallback_reason"]


def test_llm_runtime_reports_control_only_when_no_provider_available(monkeypatch):
    _disable_all(monkeypatch)
    monkeypatch.setattr(llm_runtime.settings, "openai_api_key", "")
    monkeypatch.setattr(llm_runtime.settings, "llm_primary_provider", "openai")
    monkeypatch.setattr(llm_runtime.settings, "llm_offline_provider", "ollama")
    monkeypatch.setattr(
        llm_runtime.settings, "llm_offline_base_url", "http://192.168.0.133:11434"
    )
    monkeypatch.setattr(llm_runtime.settings, "llm_offline_model", "qwen3:8b")

    def fake_get(url, headers=None, timeout=None):
        raise TimeoutError("offline")

    monkeypatch.setattr(llm_runtime.requests, "get", fake_get)

    status = llm_runtime.get_llm_runtime_status()

    assert status["mode"] == "control_only"
    assert status["active_provider_label"] == "Unavailable"
    assert "No configured LLM provider" in status["fallback_reason"]


def test_llm_runtime_uses_backup_openai_compatible(monkeypatch):
    _disable_all(monkeypatch)
    monkeypatch.setattr(llm_runtime.settings, "openai_api_key", "")
    monkeypatch.setattr(llm_runtime.settings, "llm_primary_provider", "openai")
    monkeypatch.setattr(
        llm_runtime.settings, "llm_backup_provider", "openai-compatible"
    )
    monkeypatch.setattr(
        llm_runtime.settings, "llm_backup_base_url", "http://backup.local"
    )
    monkeypatch.setattr(llm_runtime.settings, "llm_backup_model", "backup-model")
    monkeypatch.setattr(llm_runtime.settings, "llm_provider_timeout_seconds", 45)

    def fake_get(url, headers=None, timeout=None):
        assert url == "http://backup.local/v1/models"
        return DummyResponse({"data": [{"id": "backup-model"}]})

    monkeypatch.setattr(llm_runtime.requests, "get", fake_get)

    status = llm_runtime.get_llm_runtime_status()

    assert status["mode"] == "backup_online"
    assert status["active_provider_label"] == "OpenAI-compatible"
    assert status["active_model"] == "backup-model"
