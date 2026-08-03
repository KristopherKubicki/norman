from __future__ import annotations

import importlib.util
import signal
import sys
from pathlib import Path


MIB = 1024 * 1024


def _load_guard(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_local_host_pressure_guard",
        scripts_dir / "tui_local_host_pressure_guard.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_local_host_pressure_guard"] = module
    spec.loader.exec_module(module)
    return module


def _process(
    *,
    pid: int,
    ppid: int,
    start: int,
    executable: str,
    argv: list[str] | None = None,
    cwd: str = "/home/kristopher/code/control_plane",
    read_bytes: int = 0,
    write_bytes: int = 0,
    state: str = "S",
) -> dict:
    command = argv or [executable]
    return {
        "pid": pid,
        "ppid": ppid,
        "start_time_ticks": start,
        "state": state,
        "uid": 1000,
        "cwd": cwd,
        "comm": executable,
        "executable": executable,
        "argv": command,
        "command": " ".join(command),
        "read_bytes": read_bytes,
        "write_bytes": write_bytes,
    }


def _observation(
    processes: list[dict], *, checked_at_epoch: int, io_full: float = 15.0
) -> dict:
    return {
        "checked_at": f"2026-08-03T12:00:{checked_at_epoch:02d}+00:00",
        "checked_at_epoch": checked_at_epoch,
        "pressure": {
            "io": {
                "some": {"avg10": io_full + 2.0},
                "full": {"avg10": io_full},
            }
        },
        "memory": {
            "available_bytes": 28 * 1024**3,
            "swap_used_ratio": 0.9,
        },
        "root_filesystem": {
            "path": "/",
            "total_bytes": 457 * 1024**3,
            "free_bytes": 38 * 1024**3,
            "free_ratio": 0.083,
        },
        "processes": processes,
    }


def _codex_and_find(*, read_bytes: int, state: str = "S") -> list[dict]:
    return [
        _process(
            pid=100,
            ppid=1,
            start=111,
            executable="codex",
            argv=["/opt/codex", "--profile", "work"],
            read_bytes=10,
            write_bytes=10,
            state=state,
        ),
        _process(
            pid=200,
            ppid=100,
            start=222,
            executable="find",
            argv=["find", "/home"],
            read_bytes=read_bytes,
        ),
    ]


def test_first_high_sample_watches_before_pausing(monkeypatch) -> None:
    module = _load_guard(monkeypatch)
    _baseline, state, _plans = module.evaluate(
        _observation(_codex_and_find(read_bytes=0), checked_at_epoch=0, io_full=2),
        {},
        sustained_samples=2,
    )

    report, _state, plans = module.evaluate(
        _observation(_codex_and_find(read_bytes=2 * 1024 * MIB), checked_at_epoch=15),
        state,
        sustained_samples=2,
    )

    assert report["status"] == "watching"
    assert report["scan_candidates"][0]["breach_count"] == 1
    assert report["scan_candidates"][0]["eligible_to_pause"] is False
    assert plans == []


def test_second_high_sample_creates_one_action_for_codex_session(monkeypatch) -> None:
    module = _load_guard(monkeypatch)
    _baseline, state, _plans = module.evaluate(
        _observation(_codex_and_find(read_bytes=0), checked_at_epoch=0),
        {},
        sustained_samples=2,
    )
    _first, state, _plans = module.evaluate(
        _observation(_codex_and_find(read_bytes=2 * 1024 * MIB), checked_at_epoch=15),
        state,
        sustained_samples=2,
    )

    report, _state, plans = module.evaluate(
        _observation(_codex_and_find(read_bytes=4 * 1024 * MIB), checked_at_epoch=30),
        state,
        sustained_samples=2,
    )

    assert report["status"] == "offender_ready_to_pause"
    assert len(plans) == 1
    assert plans[0]["codex_pid"] == 100
    assert plans[0]["scan_processes"][0]["pid"] == 200
    assert plans[0]["resume_command"] == "kill -CONT -- 100"


def test_unattributed_broad_scan_is_alerted_but_never_paused(monkeypatch) -> None:
    module = _load_guard(monkeypatch)
    find = _process(
        pid=200,
        ppid=1,
        start=222,
        executable="find",
        argv=["find", "/tmp"],
        read_bytes=0,
    )
    _baseline, state, _plans = module.evaluate(
        _observation([find], checked_at_epoch=0),
        {},
        sustained_samples=2,
    )
    find["read_bytes"] = 2 * 1024 * MIB

    report, _state, plans = module.evaluate(
        _observation([find], checked_at_epoch=15),
        {**state, "io_pressure_count": 1},
        sustained_samples=2,
    )

    assert plans == []
    assert report["unconfirmed_high_io"][0]["pid"] == 200
    assert report["unconfirmed_high_io"][0]["reason"].startswith("no Codex ancestor")
    assert {issue["check"] for issue in report["issues"]} == {
        "io_full_pressure",
        "unconfirmed_high_io_scan",
    }


def test_high_io_pytest_is_never_an_auto_pause_candidate(monkeypatch) -> None:
    module = _load_guard(monkeypatch)
    processes = [
        _process(pid=100, ppid=1, start=111, executable="codex"),
        _process(
            pid=300,
            ppid=100,
            start=333,
            executable="pytest",
            argv=["pytest", "tests"],
            read_bytes=0,
        ),
    ]
    _baseline, state, _plans = module.evaluate(
        _observation(processes, checked_at_epoch=0),
        {},
        sustained_samples=2,
    )
    processes[1]["read_bytes"] = 2 * 1024 * MIB

    report, _state, plans = module.evaluate(
        _observation(processes, checked_at_epoch=15),
        {**state, "io_pressure_count": 1},
        sustained_samples=2,
    )

    assert plans == []
    assert report["scan_candidates"] == []
    assert report["top_agent_io"][0]["pid"] == 300
    assert report["top_process_io"][0]["pid"] == 300
    assert {issue["check"] for issue in report["issues"]} == {
        "io_full_pressure",
        "unconfirmed_high_io_process",
    }


def test_low_pressure_or_rate_remains_watch_only(monkeypatch) -> None:
    module = _load_guard(monkeypatch)
    _baseline, state, _plans = module.evaluate(
        _observation(_codex_and_find(read_bytes=0), checked_at_epoch=0, io_full=2),
        {},
        sustained_samples=2,
    )

    report, _state, plans = module.evaluate(
        _observation(
            _codex_and_find(read_bytes=10 * MIB), checked_at_epoch=15, io_full=2
        ),
        state,
        sustained_samples=2,
    )

    assert report["status"] == "healthy"
    assert report["scan_candidates"][0]["breach_count"] == 0
    assert plans == []


def test_rg_pattern_is_not_mistaken_for_a_broad_path(monkeypatch) -> None:
    module = _load_guard(monkeypatch)
    processes = [
        _process(pid=100, ppid=1, start=111, executable="codex"),
        _process(
            pid=200,
            ppid=100,
            start=222,
            executable="rg",
            argv=["rg", "/home"],
            read_bytes=0,
        ),
        _process(
            pid=201,
            ppid=100,
            start=223,
            executable="rg",
            argv=["rg", "needle", "/home"],
            read_bytes=0,
        ),
        _process(
            pid=202,
            ppid=100,
            start=224,
            executable="rg",
            argv=["rg", "--regexp", "/home", "/tmp"],
            read_bytes=0,
        ),
    ]
    _baseline, state, _plans = module.evaluate(
        _observation(processes, checked_at_epoch=0),
        {},
        sustained_samples=2,
    )
    processes[1]["read_bytes"] = 2 * 1024 * MIB
    processes[2]["read_bytes"] = 2 * 1024 * MIB
    processes[3]["read_bytes"] = 2 * 1024 * MIB

    report, _state, _plans = module.evaluate(
        _observation(processes, checked_at_epoch=15),
        state,
        sustained_samples=2,
    )

    assert [candidate["pid"] for candidate in report["scan_candidates"]] == [201, 202]
    assert report["scan_candidates"][0]["broad_targets"] == ["/home"]
    assert report["scan_candidates"][1]["broad_targets"] == ["/tmp"]


def test_find_expression_operand_is_not_mistaken_for_a_starting_path(
    monkeypatch,
) -> None:
    module = _load_guard(monkeypatch)
    processes = [
        _process(pid=100, ppid=1, start=111, executable="codex"),
        _process(
            pid=200,
            ppid=100,
            start=222,
            executable="find",
            argv=["find", "-name", "/home"],
            read_bytes=0,
        ),
    ]
    _baseline, state, _plans = module.evaluate(
        _observation(processes, checked_at_epoch=0),
        {},
        sustained_samples=2,
    )
    processes[1]["read_bytes"] = 2 * 1024 * MIB

    report, _state, plans = module.evaluate(
        _observation(processes, checked_at_epoch=15),
        state,
        sustained_samples=2,
    )

    assert report["scan_candidates"] == []
    assert plans == []


def test_apply_action_interrupts_scan_before_pausing_codex(monkeypatch) -> None:
    module = _load_guard(monkeypatch)
    action = {
        "action": "interrupt_scan_and_pause_codex",
        "codex_pid": 100,
        "codex_start_time_ticks": 111,
        "scan_processes": [
            {
                "pid": 200,
                "start_time_ticks": 222,
                "command": "find /home",
                "broad_targets": ["/home"],
                "read_bytes_per_second": 200 * MIB,
            }
        ],
        "resume_command": "kill -CONT -- 100",
        "cancel_command": "kill -TERM -- 100",
    }
    calls: list[tuple[int, signal.Signals]] = []

    def identity(pid: int):
        return {100: (111, "S"), 200: (222, "R")}.get(pid)

    result = module.apply_action_plan(
        action,
        identity_fn=identity,
        signal_fn=lambda pid, value: calls.append((pid, value)),
    )

    assert result["applied"] is True
    assert result["result"] == "scan_interrupted_codex_paused"
    assert calls == [(200, signal.SIGINT), (100, signal.SIGSTOP)]


def test_pid_start_time_mismatch_prevents_signals(monkeypatch) -> None:
    module = _load_guard(monkeypatch)
    action = {
        "codex_pid": 100,
        "codex_start_time_ticks": 111,
        "scan_processes": [{"pid": 200, "start_time_ticks": 222}],
    }
    calls: list[tuple[int, signal.Signals]] = []

    result = module.apply_action_plan(
        action,
        identity_fn=lambda _pid: (999, "S"),
        signal_fn=lambda pid, value: calls.append((pid, value)),
    )

    assert result["applied"] is False
    assert result["result"] == "codex_identity_changed"
    assert calls == []


def test_report_has_kpis_and_systemd_units_enforce_local_scope(monkeypatch) -> None:
    module = _load_guard(monkeypatch)
    report, _state, _plans = module.evaluate(
        _observation([], checked_at_epoch=100),
        {},
    )
    root = Path(__file__).resolve().parents[1]
    service = (
        root / "scripts" / "systemd" / "norman-tui-local-host-pressure-guard.service"
    ).read_text(encoding="utf-8")
    timer = (
        root / "scripts" / "systemd" / "norman-tui-local-host-pressure-guard.timer"
    ).read_text(encoding="utf-8")
    alert_service = (
        root / "scripts" / "systemd" / "norman-tui-local-host-pressure-alerts.service"
    ).read_text(encoding="utf-8")
    alert_path = (
        root / "scripts" / "systemd" / "norman-tui-local-host-pressure-alerts.path"
    ).read_text(encoding="utf-8")

    assert report["schema"] == "norman.tui.local-host-pressure-guard.v1"
    assert report["kpis"]["io_full_avg10"] == 15.0
    assert report["admission"]["action"] == "defer_background_work"
    assert "User=kristopher" in service
    assert "IOSchedulingClass=idle" in service
    assert "Nice=19" in service
    assert "tui_local_host_pressure_guard.py --apply" in service
    assert "OnUnitActiveSec=15s" in timer
    assert "Persistent=true" in timer
    assert "tui_fleet_alerts.py" in alert_service
    assert '"--title=Norman local host pressure"' in alert_service
    assert "--warn-threshold 1" in alert_service
    assert "PathChanged=/home/kristopher/.local/state/norman/" in alert_path
