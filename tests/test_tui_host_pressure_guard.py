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
    assert "pct reboot" not in service
    assert "pct stop" not in service
    assert "OnUnitActiveSec=1m" in timer
