from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "agent_console_template"
    / "agent_console_session_budget.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "agent_console_session_budget_standalone",
        MODULE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_standalone_model_capability_uses_adjacent_registry(
    monkeypatch,
    tmp_path,
) -> None:
    registry = tmp_path / "model_roles.json"
    registry.write_text(
        json.dumps(
            {
                "schema": "norman.norllama.model-roles.v1",
                "roles": {
                    "resident": {"model": "future-local", "capabilities": {}},
                    "economy": {"model": "future-luna", "capabilities": {}},
                    "authority": {
                        "model": "future-terra",
                        "aliases": ["future-authority"],
                        "capabilities": {"named_escalation_required": True},
                    },
                    "frontier": {"model": "future-sol", "capabilities": {}},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NORMAN_MODEL_ROLE_CONFIG", str(registry))
    module = _load_module()

    assert module.model_requires_named_escalation("future-terra") is True
    assert module.model_requires_named_escalation("future-authority") is True
    assert module.model_requires_named_escalation("unknown-model") is False


def test_standalone_model_capability_fails_conservatively_without_registry(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(
        "NORMAN_MODEL_ROLE_CONFIG",
        str(tmp_path / "missing-model-roles.json"),
    )
    module = _load_module()

    assert module.model_requires_named_escalation("unknown-model") is False
