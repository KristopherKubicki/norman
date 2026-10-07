from pathlib import Path
import tomllib

import pytest

from scripts.codex_work_gateway import (
    WORK_ENDPOINT,
    update_profile,
    work_gateway_profile,
)


@pytest.mark.parametrize(
    "provider",
    [
        "",
        """[model_providers.norman]
name = "Keystone"
base_url = "https://keystone.kris.openbrand.com/v1"
stream_idle_timeout_ms = 1200000
[model_providers.norman.auth]
args = ["--secret", "compere/prompt-proxy-token"]
timeout_ms = 15000
""",
    ],
)
def test_work_contract_preserves_model_mcp_and_custom_settings(provider):
    contents = (
        'model = "norman-code-astra"\nmodel_provider = "norman"\n'
        + provider
        + """
[mcp_servers.example]
command = "existing-command"
"""
    )
    result = work_gateway_profile(contents, Path("/helper"))
    data = tomllib.loads(result)
    assert data["model"] == "norman-code-astra"
    assert data["mcp_servers"]["example"]["command"] == "existing-command"
    gateway = data["model_providers"]["norman"]
    assert gateway["base_url"] == WORK_ENDPOINT
    assert gateway["auth"]["args"] == ["--secret", "norman/prompt-proxy-token"]
    if provider:
        assert gateway["stream_idle_timeout_ms"] == 1200000
        assert gateway["auth"]["timeout_ms"] == 15000
    assert work_gateway_profile(result, Path("/helper")) == result
    assert "keystone" not in result and "compere" not in result


def test_invalid_profile_is_not_replaced(tmp_path):
    path = tmp_path / "work.config.toml"
    path.write_text("invalid = [")
    with pytest.raises(ValueError):
        update_profile(path)
    assert path.read_text() == "invalid = ["


def test_profile_update_is_private_and_leaves_history_alone(tmp_path):
    path = tmp_path / "work.config.toml"
    history = tmp_path / "history.jsonl"
    path.write_text('model_provider = "norman"\n')
    history.write_text("existing session")
    update_profile(path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert history.read_text() == "existing session"
