from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "norllama" / "fleet_health.py"
    spec = importlib.util.spec_from_file_location("fleet_health", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _healthy_payload() -> dict[str, object]:
    policy = {
        "integrity_valid": True,
        "default_route_allowed": True,
        "production_route_eligible": True,
        "validation": {"seconds_to_expiry": 7 * 24 * 60 * 60},
    }
    return {
        "endpoints": {
            "/healthz": {"status": 200, "json": {}},
            "/readyz": {"status": 200, "json": {"ready": True, "policy": policy}},
            "/asr-readyz": {"status": 200, "json": {"ready": True}},
            "/v1/models": {"status": 200, "json": {}},
        },
        "services": {
            "gateway": {"active": True, "restarts": 0},
            "asr": {"active": True, "restarts": 0},
        },
        "resources": {"mem_available_kib": 9 * 1024 * 1024},
    }


def test_collect_reports_healthy_linux_worker(monkeypatch) -> None:
    module = _load_module()
    target = module.DEFAULT_TARGETS[0]
    monkeypatch.setattr(module, "probe_target", lambda _target: _healthy_payload())

    report = module.collect((target,))

    assert report["status"] == "ok"
    assert report["summary"] == {"active": 1, "expected": 1, "fail": 0, "warn": 0}
    assert report["targets"][0]["healthy"] is True


def test_collect_surfaces_policy_expiry_and_memory_pressure(monkeypatch) -> None:
    module = _load_module()
    target = module.DEFAULT_TARGETS[0]
    payload = _healthy_payload()
    payload["endpoints"]["/readyz"]["json"]["policy"]["validation"]["seconds_to_expiry"] = 60
    payload["resources"]["mem_available_kib"] = 3 * 1024 * 1024
    monkeypatch.setattr(module, "probe_target", lambda _target: payload)

    report = module.collect((target,))

    assert report["status"] == "degraded"
    assert {issue["check"] for issue in report["issues"]} == {"policy:expiry", "memory"}


def test_collect_fails_when_gateway_endpoint_or_service_is_down(monkeypatch) -> None:
    module = _load_module()
    target = module.DEFAULT_TARGETS[0]
    payload = _healthy_payload()
    payload["endpoints"]["/asr-readyz"] = {"status": 503, "error": "unavailable"}
    payload["services"]["asr"]["active"] = False
    monkeypatch.setattr(module, "probe_target", lambda _target: payload)

    report = module.collect((target,))

    assert report["status"] == "failed"
    assert report["summary"]["active"] == 0
    assert {issue["check"] for issue in report["issues"]} >= {
        "endpoint:/asr-readyz",
        "service:asr",
    }
