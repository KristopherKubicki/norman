from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "local_runtime_health.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("local_runtime_health", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ollama_sense_fallback_marks_lan_endpoint_routeable(monkeypatch) -> None:
    module = load_module()

    def fake_read_json_url(url: str, *, timeout_seconds: float = 1.5):
        return False, {}, "connection refused"

    monkeypatch.setattr(module, "_read_json_url", fake_read_json_url)
    report = module.build_report(
        ollama_sense_report={
            "schema": "norman.tui.ollama-sense.v1",
            "summary": {"best_endpoint": "http://192.168.2.133:11434"},
            "endpoints": [
                {
                    "endpoint": "http://192.168.2.133:11434",
                    "scope": "lan",
                    "usable": True,
                    "models": ["qwen3:8b", "gemma3:4b"],
                    "latency_ms": 44,
                }
            ],
        }
    )

    ollama = report["runtimes"][0]
    assert ollama["runtime_class"] == "ollama"
    assert ollama["status"] == "healthy"
    assert ollama["routeable"] is True
    assert ollama["endpoint"] == "http://192.168.2.133:11434"
    assert ollama["model_count"] == 2
    assert ollama["health_source"] == "ollama_sense_fallback"
    assert ollama["endpoint_scope"] == "lan"
    assert report["summary"]["healthy_runtime_count"] == 1
    assert report["summary"]["routeable_runtime_classes"] == ["ollama"]
