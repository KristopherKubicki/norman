from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "norllama"
        / "refresh_fleet_route_policy.py"
    )
    spec = importlib.util.spec_from_file_location("refresh_fleet_route_policy", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dry_run_generates_the_next_common_generation(monkeypatch) -> None:
    module = _load_module()
    targets = module.TARGETS[:2]

    def fake_http(url: str):
        generation = 4 if "150" in url else 7
        return 200, {"ready": True, "policy": {"refresh_generation": generation}}

    monkeypatch.setattr(module, "http_json", fake_http)

    report = module.refresh(targets=targets, apply=False)

    assert report["status"] == "ok"
    assert report["refresh_generation"] == 8
    assert [target["status"] for target in report["targets"]] == ["planned", "planned"]
    assert report["validation"]["production_route_eligible"] is True


def test_refresh_report_adapts_failures_to_the_alert_contract() -> None:
    module = _load_module()

    report = module.add_alert_contract(
        {"mode": "apply", "status": "blocked", "error": "simulated SSH failure"}
    )

    assert report["summary"]["fail"] == 1
    assert report["issues"][0]["check"] == "refresh"


def test_refresh_blocks_when_a_worker_is_not_ready(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "http_json", lambda _url: (503, {}))

    report = module.refresh(targets=module.TARGETS[:1], apply=False)

    assert report["status"] == "blocked"
    assert "preflight" in report["error"]
