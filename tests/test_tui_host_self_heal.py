from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_self_heal(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_host_self_heal", scripts_dir / "tui_host_self_heal.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_host_self_heal"] = module
    spec.loader.exec_module(module)
    return module


def _health(*issues: dict, checked_at: str = "2026-06-19T16:00:00Z") -> dict:
    return {"checked_at": checked_at, "issues": list(issues)}


def _scan_fail() -> dict:
    return {
        "severity": "fail",
        "host": "work-special",
        "instance": "<host>",
        "check": "scan",
        "detail": "CalledProcessError: SSH banner timeout; recovery available: scripts/tui_host_recovery.py --target work-special",
    }


def _pressure_fail() -> dict:
    return {
        "severity": "fail",
        "host": "work-special",
        "instance": "<host>",
        "check": "host-pressure",
        "detail": "critical host pressure; io_some=97.93 >= critical 80",
    }


def _wedged_observation() -> dict:
    return {
        "pct_status": {"returncode": 0, "stdout": "status: running"},
        "probes": {
            "work-special.home.arpa:22": "connected; no SSH banner within 2s",
            "work-special.home.arpa:80": "connected; no HTTP bytes within 2s",
        },
        "pvesh_status_json": {
            "pressureiosome": "94.05",
            "pressurememorysome": "61.28",
        },
    }


def _healthy_observation() -> dict:
    return {
        "pct_status": {"returncode": 0, "stdout": "status: running"},
        "probes": {
            "work-special.home.arpa:22": "responded",
            "work-special.home.arpa:80": "responded",
        },
        "pvesh_status_json": {
            "pressureiosome": "1.00",
            "pressurememorysome": "0.00",
        },
    }


def test_self_heal_waits_for_repeated_recoverable_failure(monkeypatch) -> None:
    module = _load_self_heal(monkeypatch)

    decision, state = module.evaluate(
        _health(_scan_fail()),
        {},
        target_name="work-special",
        failure_threshold=2,
        execute=False,
        approved=False,
        settle_seconds=0,
    )

    assert decision["status"] == "watching"
    assert decision["action"] == "none"
    assert state["targets"]["work-special"]["failure_count"] == 1


def test_self_heal_second_failure_would_recover_after_wedge_observation(
    monkeypatch,
) -> None:
    module = _load_self_heal(monkeypatch)
    state = {
        "targets": {
            "work-special": {
                "failure_count": 1,
                "last_checked_at": "2026-06-19T16:00:00Z",
                "last_signatures": [],
            }
        }
    }

    decision, next_state = module.evaluate(
        _health(_pressure_fail(), checked_at="2026-06-19T16:05:00Z"),
        state,
        target_name="work-special",
        failure_threshold=2,
        execute=False,
        approved=False,
        settle_seconds=0,
        observe_fn=lambda _target: _wedged_observation(),
    )

    assert decision["status"] == "would_recover"
    assert decision["action"] == "graceful_reboot"
    assert decision["execute_required"] is True
    assert next_state["targets"]["work-special"]["failure_count"] == 2


def test_self_heal_does_not_reboot_when_observation_has_recovered(monkeypatch) -> None:
    module = _load_self_heal(monkeypatch)
    state = {
        "targets": {
            "work-special": {
                "failure_count": 1,
                "last_checked_at": "2026-06-19T16:00:00Z",
                "last_signatures": [],
            }
        }
    }

    decision, _state = module.evaluate(
        _health(_scan_fail(), checked_at="2026-06-19T16:05:00Z"),
        state,
        target_name="work-special",
        failure_threshold=2,
        execute=True,
        approved=True,
        settle_seconds=0,
        observe_fn=lambda _target: _healthy_observation(),
    )

    assert decision["status"] == "not_wedged"
    assert decision["action"] == "none"


def test_self_heal_executes_only_graceful_reboot_when_approved(monkeypatch) -> None:
    module = _load_self_heal(monkeypatch)
    calls: list[str] = []
    state = {
        "targets": {
            "work-special": {
                "failure_count": 1,
                "last_checked_at": "2026-06-19T16:00:00Z",
                "last_signatures": [],
            }
        }
    }

    def fake_reboot(target):
        calls.append(target.name)
        return module.recovery.CommandResult(
            command=["pct", "reboot", "147", "--timeout", "60"],
            returncode=0,
            stdout="",
            stderr="",
        )

    decision, next_state = module.evaluate(
        _health(_scan_fail(), checked_at="2026-06-19T16:05:00Z"),
        state,
        target_name="work-special",
        failure_threshold=2,
        execute=True,
        approved=True,
        settle_seconds=0,
        observe_fn=lambda _target: _wedged_observation()
        if not calls
        else _healthy_observation(),
        reboot_fn=fake_reboot,
    )

    assert calls == ["work-special"]
    assert decision["status"] == "recovered"
    assert decision["action_result"]["command"] == [
        "pct",
        "reboot",
        "147",
        "--timeout",
        "60",
    ]
    assert next_state["targets"]["work-special"]["failure_count"] == 0


def test_self_heal_cli_requires_approval_for_execute(monkeypatch, tmp_path, capsys):
    module = _load_self_heal(monkeypatch)
    health = tmp_path / "health.json"
    health.write_text(json.dumps(_health(_scan_fail())), encoding="utf-8")

    assert (
        module.main(
            [
                "--target",
                "work-special",
                "--health-json",
                str(health),
                "--state",
                str(tmp_path / "state.json"),
                "--json-output",
                str(tmp_path / "out.json"),
                "--execute",
            ]
        )
        == 2
    )
    assert "--execute requires --approved" in capsys.readouterr().err


def test_self_heal_systemd_unit_is_graceful_only() -> None:
    root = Path(__file__).resolve().parents[1]
    service = (
        root / "scripts" / "systemd" / "norman-tui-host-self-heal.service"
    ).read_text(encoding="utf-8")
    path = (root / "scripts" / "systemd" / "norman-tui-host-self-heal.path").read_text(
        encoding="utf-8"
    )

    assert "scripts/tui_host_self_heal.py" in service
    assert "--target work-special" in service
    assert "--execute --approved" in service
    assert "pct stop" not in service
    assert (
        "PathChanged=/home/kristopher/.local/state/norman/tui-fleet-doctor.json" in path
    )
    assert "Unit=norman-tui-host-self-heal.service" in path
