from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from app.services.norllama.route_policy_artifact import (
    generate_route_policy_artifact,
    write_route_policy_artifact,
)


def _load_script():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "norllama"
        / "refresh_route_policy.py"
    )
    spec = importlib.util.spec_from_file_location("refresh_route_policy", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_refresh_command_writes_route_eligible_policy(tmp_path, capsys):
    module = _load_script()
    path = tmp_path / "route_policy.json"
    write_route_policy_artifact(generate_route_policy_artifact(), path)

    assert module.main(["--path", str(path)]) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "ok"
    assert summary["path"] == str(path)
    assert summary["default_route_allowed"] is True
    assert summary["production_route_eligible"] is True
    assert summary["refresh_generation"] > summary["previous_generation"]


def test_refresh_command_returns_nonzero_when_refresh_is_not_eligible(
    monkeypatch, tmp_path, capsys
):
    module = _load_script()
    monkeypatch.setattr(
        module,
        "refresh_route_policy_artifact",
        lambda _path: {
            "active_generation": 4,
            "previous_generation": 3,
            "last_refresh_success": "",
            "last_refresh_error": "simulated write failure",
            "write": {"ok": False, "error": "simulated write failure"},
            "policy": {},
            "validation": {
                "state": "expired_blocked",
                "default_route_allowed": False,
                "production_route_eligible": False,
            },
        },
    )

    assert module.main(["--path", str(tmp_path / "route_policy.json")]) == 2

    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "blocked"
    assert summary["validation_state"] == "expired_blocked"
    assert summary["error"] == "simulated write failure"


def test_refresh_command_runs_outside_the_checkout(tmp_path):
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "norllama"
        / "refresh_route_policy.py"
    )
    policy_path = tmp_path / "route_policy.json"

    result = subprocess.run(
        [sys.executable, str(script), "--path", str(policy_path)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "ok"
    assert summary["path"] == str(policy_path)
