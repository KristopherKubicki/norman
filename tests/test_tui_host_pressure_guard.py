from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_guard(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_host_pressure_guard", scripts_dir / "tui_host_pressure_guard.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_host_pressure_guard"] = module
    spec.loader.exec_module(module)
    return module


def _observation(**status):
    return {"pvesh_status_json": status}


def test_pressure_guard_watches_early_swap_use(monkeypatch) -> None:
    module = _load_guard(monkeypatch)

    decision, state = module.evaluate(
        _observation(
            mem=2 * 1024**3,
            maxmem=6 * 1024**3,
            swap=128 * 1024**2,
            maxswap=2 * 1024**3,
            pressurememorysome="0.00",
            pressureiosome="0.00",
        ),
        {},
        target_name="work-special",
        critical_threshold=2,
        observed_at=100,
    )

    assert decision["status"] == "watching"
    assert decision["admission"]["action"] == "accept_new_work"
    assert "swap_used_ratio>0" in decision["watch_reasons"]
    assert state["targets"]["work-special"]["critical_count"] == 0


def test_pressure_guard_defers_heavy_work_on_elevated_swap(monkeypatch) -> None:
    module = _load_guard(monkeypatch)

    decision, _state = module.evaluate(
        _observation(
            mem=2 * 1024**3,
            maxmem=6 * 1024**3,
            swap=768 * 1024**2,
            maxswap=2 * 1024**3,
            pressurememorysome="0.00",
            pressureiofull="12.00",
            pressureiosome="20.00",
        ),
        {},
        target_name="work-special",
        critical_threshold=2,
        observed_at=100,
    )

    assert decision["status"] == "watching"
    assert decision["admission"]["action"] == "defer_heavy_work"
    assert "swap_used_ratio>=0.25" in decision["watch_reasons"]


def test_pressure_guard_blocks_after_repeated_critical_pressure(monkeypatch) -> None:
    module = _load_guard(monkeypatch)
    critical = _observation(
        mem=5 * 1024**3,
        maxmem=6 * 1024**3,
        swap=1536 * 1024**2,
        maxswap=2 * 1024**3,
        pressurememorysome="61.00",
        pressureiosome="81.00",
    )

    first, state = module.evaluate(
        critical,
        {},
        target_name="work-special",
        critical_threshold=2,
        observed_at=100,
    )
    second, state = module.evaluate(
        critical,
        state,
        target_name="work-special",
        critical_threshold=2,
        observed_at=160,
    )

    assert first["status"] == "critical_watching"
    assert first["admission"]["action"] == "defer_heavy_work"
    assert second["status"] == "critical"
    assert second["admission"]["action"] == "block_new_work"
    assert state["targets"]["work-special"]["critical_count"] == 2


def test_pressure_guard_falls_back_to_local_pressure_when_pvesh_omits_metrics(
    monkeypatch,
) -> None:
    module = _load_guard(monkeypatch)

    decision, _state = module.evaluate(
        _observation(
            mem=None,
            maxmem=None,
            swap=None,
            maxswap=None,
            pressurememorysome=None,
            pressurememoryfull=None,
            pressureiosome=None,
            pressureiofull=None,
        ),
        {},
        target_name="work-special",
        critical_threshold=2,
        observed_at=100,
        local_current={
            "mem": 5 * 1024**3,
            "maxmem": 6 * 1024**3,
            "swap": 1536 * 1024**2,
            "maxswap": 2 * 1024**3,
            "pressurememorysome": 61.0,
            "pressurememoryfull": 22.0,
            "pressureiosome": 92.0,
            "pressureiofull": 60.0,
        },
    )

    assert decision["status"] == "critical_watching"
    assert decision["admission"]["action"] == "defer_heavy_work"
    assert "io_some>=80" in decision["critical_reasons"]
    assert "memory_full>=20" in decision["critical_reasons"]
    assert decision["sample"]["sources"]["pressureiosome"] == "local"
    assert decision["sample"]["sources"]["mem"] == "local"


def test_local_pressure_status_reads_proc_psi_and_memory(monkeypatch, tmp_path) -> None:
    module = _load_guard(monkeypatch)
    pressure_dir = tmp_path / "pressure"
    pressure_dir.mkdir()
    (tmp_path / "meminfo").write_text(
        "MemTotal:        8192 kB\n"
        "MemAvailable:    2048 kB\n"
        "SwapTotal:       4096 kB\n"
        "SwapFree:        1024 kB\n",
        encoding="utf-8",
    )
    (pressure_dir / "cpu").write_text(
        "some avg10=1.50 avg60=1.00 avg300=0.50 total=1\n",
        encoding="utf-8",
    )
    (pressure_dir / "io").write_text(
        "some avg10=92.00 avg60=1.00 avg300=0.50 total=1\n"
        "full avg10=60.00 avg60=1.00 avg300=0.50 total=1\n",
        encoding="utf-8",
    )
    (pressure_dir / "memory").write_text(
        "some avg10=23.00 avg60=1.00 avg300=0.50 total=1\n"
        "full avg10=22.00 avg60=1.00 avg300=0.50 total=1\n",
        encoding="utf-8",
    )

    current = module.local_pressure_status(proc_root=tmp_path)

    assert current == {
        "mem": 6 * 1024**2,
        "maxmem": 8 * 1024**2,
        "swap": 3 * 1024**2,
        "maxswap": 4 * 1024**2,
        "pressurecpusome": 1.5,
        "pressureiosome": 92.0,
        "pressurememorysome": 23.0,
        "pressurememoryfull": 22.0,
        "pressureiofull": 60.0,
    }


def test_pressure_guard_systemd_timer_is_non_destructive() -> None:
    root = Path(__file__).resolve().parents[1]
    service = (
        root / "scripts" / "systemd" / "norman-tui-host-pressure-guard.service"
    ).read_text(encoding="utf-8")
    timer = (
        root / "scripts" / "systemd" / "norman-tui-host-pressure-guard.timer"
    ).read_text(encoding="utf-8")

    assert "scripts/tui_host_pressure_guard.py" in service
    assert "--target work-special" in service
    assert "User=kristopher" in service
    assert "pct reboot" not in service
    assert "pct stop" not in service
    assert "OnUnitActiveSec=1m" in timer
