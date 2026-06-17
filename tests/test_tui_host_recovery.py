from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_recovery(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_host_recovery", scripts_dir / "tui_host_recovery.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_host_recovery"] = module
    spec.loader.exec_module(module)
    return module


def test_recovery_plan_is_observe_only_by_default(monkeypatch) -> None:
    module = _load_recovery(monkeypatch)
    target = module.RECOVERY_TARGETS["work-special"]

    plan = module.recovery_plan(target)

    assert plan["approval_required"] is True
    assert plan["default_mode"] == "observe_only"
    assert plan["first_action"]["command"][-5:] == [
        "pct",
        "reboot",
        "147",
        "--timeout",
        "60",
    ]


def test_recovery_commands_use_the_explicit_norman_identity(monkeypatch) -> None:
    module = _load_recovery(monkeypatch)
    target = module.RECOVERY_TARGETS["work-special"]

    command = module.pct_command(target, "status", target.container_id)

    assert command[:3] == [
        "ssh",
        "-i",
        str(Path("~/.ssh/norman_tui_deploy_ed25519").expanduser()),
    ]
    assert "IdentitiesOnly=yes" in command
    assert "root@proxmox.home.arpa" in command
    assert command[-3:] == ["pct", "status", "147"]


def test_pvesh_status_uses_configured_proxmox_node_name(monkeypatch) -> None:
    module = _load_recovery(monkeypatch)
    target = module.RECOVERY_TARGETS["work-special"]

    command = module.pvesh_current_status_command(target)

    assert "/nodes/vm/lxc/147/status/current" in command


def test_execute_requires_explicit_approval(monkeypatch, capsys) -> None:
    module = _load_recovery(monkeypatch)

    assert module.main(["--target", "work-special", "--execute"]) == 2

    assert "--execute requires --approved" in capsys.readouterr().err


def test_payload_renders_pressure_when_proxmox_reports_it(monkeypatch) -> None:
    module = _load_recovery(monkeypatch)
    target = module.RECOVERY_TARGETS["work-special"]
    payload = module.build_payload(
        target,
        mode="observe_only",
        observation={
            "probes": {"work-special.home.arpa:80": "responded"},
            "pct_status": {"returncode": 0, "stdout": "status: running"},
            "pvesh_status_json": {
                "pressurecpusome": "30.10",
                "pressureiosome": "40.91",
                "pressurememorysome": "0.00",
            },
        },
    )

    rendered = module.render_markdown(payload)

    assert "Mode: `observe_only`" in rendered
    assert "work-special.home.arpa:80: responded" in rendered
    assert "pressure: cpu_some=30.10 io_some=40.91 mem_some=0.00" in rendered
