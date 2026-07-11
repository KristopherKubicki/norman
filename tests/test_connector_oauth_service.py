import pytest

from app.services import connector_oauth


def test_oauth_capability_gates_google_connectors(monkeypatch):
    monkeypatch.setattr(
        connector_oauth,
        "_provider_configured",
        lambda provider: provider in {"google", "microsoft"},
    )
    capability = connector_oauth.oauth_capability("gmail")
    assert capability is not None
    assert capability["providers"] == ["google"]
    assert capability["default_provider"] == "google"
    assert "google" in capability["scopes_by_provider"]


def test_oauth_capability_gates_microsoft_connectors(monkeypatch):
    monkeypatch.setattr(
        connector_oauth,
        "_provider_configured",
        lambda provider: provider in {"google", "microsoft"},
    )
    capability = connector_oauth.oauth_capability("teams")
    assert capability is not None
    assert capability["providers"] == ["microsoft"]
    assert capability["default_provider"] == "microsoft"
    assert "microsoft" in capability["scopes_by_provider"]


def test_resolve_oauth_binding_rejects_irrelevant_provider(monkeypatch):
    monkeypatch.setattr(
        connector_oauth,
        "_provider_configured",
        lambda provider: provider in {"google", "microsoft"},
    )
    with pytest.raises(ValueError):
        connector_oauth.resolve_oauth_binding("teams", provider="google")
