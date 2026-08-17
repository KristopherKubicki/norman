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


def test_stage_only_writes_next_policy_without_promoting_live(
    monkeypatch, tmp_path
) -> None:
    module = _load_module()
    target = {
        "name": "worker-a",
        "policy_path": "/srv/norllama/route_policy.json",
        "url": "http://worker-a:18151",
    }
    staged_calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        module,
        "http_json",
        lambda _url: (
            200,
            {
                "ready": True,
                "policy": {"refresh_generation": 9},
            },
        ),
    )
    monkeypatch.setattr(
        module,
        "copy_to_remote",
        lambda _path, _target, _destination: type(
            "Result", (), {"returncode": 0, "stderr": ""}
        )(),
    )
    monkeypatch.setattr(
        module,
        "remote_checksum",
        lambda _target, _path, _sha256: (True, ""),
    )

    def fake_stage(_target, staged, pending, backup):
        staged_calls.append((staged, pending, backup))
        return True, ""

    monkeypatch.setattr(module, "stage_for_activation", fake_stage)
    monkeypatch.setattr(
        module,
        "promote",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("stage-only refresh must not promote live policy")
        ),
    )
    monkeypatch.setattr(module, "cleanup", lambda *_args: None)

    report = module.refresh(targets=[target], apply=True, stage_only=True)

    assert report["status"] == "ok"
    assert report["mode"] == "stage"
    assert report["targets"] == [{"name": "worker-a", "status": "staged"}]
    assert staged_calls[0][0] == "/srv/norllama/route_policy.next.json"


def test_next_policy_path_matches_gateway_deployment_convention() -> None:
    module = _load_module()

    assert (
        module.next_policy_path("/srv/norllama/route_policy.json")
        == "/srv/norllama/route_policy.next.json"
    )


def test_failed_partial_stage_reports_full_expected_fleet() -> None:
    module = _load_module()

    report = module.add_alert_contract(
        {
            "mode": "stage",
            "status": "blocked",
            "preflight": [{}, {}, {}],
            "targets": [
                {"name": "worker-a", "status": "staged"},
                {"name": "worker-b", "status": "staged"},
            ],
        }
    )

    assert report["summary"]["active"] == 2
    assert report["summary"]["expected"] == 3


def test_alert_contract_counts_staged_targets_as_healthy() -> None:
    module = _load_module()

    report = module.add_alert_contract(
        {
            "mode": "stage",
            "status": "ok",
            "targets": [{"name": "worker-a", "status": "staged"}],
        }
    )

    assert report["summary"] == {
        "active": 1,
        "expected": 1,
        "fail": 0,
        "warn": 0,
    }
