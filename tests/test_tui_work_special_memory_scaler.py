from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_scaler(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_work_special_memory_scaler",
        scripts_dir / "tui_work_special_memory_scaler.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_work_special_memory_scaler"] = module
    spec.loader.exec_module(module)
    return module


def _current(module, *, mem_mib=7600, max_mib=8192, swap_mib=0, psi=0):
    return {
        "mem": mem_mib * module.MIB,
        "maxmem": max_mib * module.MIB,
        "swap": swap_mib * module.MIB,
        "maxswap": 4096 * module.MIB,
        "pressurememorysome": str(psi),
    }


def _node(module, *, available_gib=8):
    return {"memory": {"available": available_gib * module.GIB}}


def test_scaler_requires_sustained_pressure_before_growth(monkeypatch) -> None:
    module = _load_scaler(monkeypatch)
    decision, state = module.evaluate(
        _current(module, mem_mib=7600, psi=25),
        _node(module),
        {},
    )

    assert decision["action"] == "watch"
    assert decision["candidate_memory_mib"] == 9216
    assert state["sustained_pressure_samples"] == 1


def test_scaler_grows_only_after_pressure_and_node_reserve(monkeypatch) -> None:
    module = _load_scaler(monkeypatch)
    _first, state = module.evaluate(
        _current(module, mem_mib=7600, psi=25),
        _node(module),
        {},
    )
    decision, _state = module.evaluate(
        _current(module, mem_mib=7600, psi=25),
        _node(module, available_gib=8),
        state,
    )

    assert decision["action"] == "grow"
    assert decision["candidate_memory_mib"] == 9216
    assert decision["headroom_ok"] is True


def test_scaler_holds_when_node_reserve_would_be_violated(monkeypatch) -> None:
    module = _load_scaler(monkeypatch)
    decision, _state = module.evaluate(
        _current(module, mem_mib=7600, psi=25),
        _node(module, available_gib=4),
        {"sustained_pressure_samples": 1},
    )

    assert decision["action"] == "hold"
    assert decision["headroom_ok"] is False


def test_scaler_never_shrinks_when_pressure_normal(monkeypatch) -> None:
    module = _load_scaler(monkeypatch)
    decision, state = module.evaluate(
        _current(module, mem_mib=2000, max_mib=8192),
        _node(module),
        {"sustained_pressure_samples": 4},
    )

    assert decision["action"] == "none"
    assert "never auto-shrink" in decision["reason"]
    assert state["sustained_pressure_samples"] == 0


def test_scaler_systemd_unit_is_bounded_and_non_destructive() -> None:
    root = Path(__file__).resolve().parents[1]
    service = (
        root / "scripts" / "systemd" / "norman-tui-work-special-memory-scaler.service"
    ).read_text(encoding="utf-8")
    timer = (
        root / "scripts" / "systemd" / "norman-tui-work-special-memory-scaler.timer"
    ).read_text(encoding="utf-8")

    assert "tui_work_special_memory_scaler.py --apply" in service
    assert "User=kristopher" in service
    assert "pct stop" not in service
    assert "pct reboot" not in service
    assert "OnUnitActiveSec=1m" in timer
