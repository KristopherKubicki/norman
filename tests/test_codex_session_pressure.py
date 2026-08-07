from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


MIB = 1024 * 1024


def _load_module(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "codex_session_pressure", scripts_dir / "codex_session_pressure.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["codex_session_pressure"] = module
    spec.loader.exec_module(module)
    return module


def _active_proc(proc_root: Path, pid: int, session: Path, *, pss_mib: int) -> None:
    process = proc_root / str(pid)
    fd_dir = process / "fd"
    fd_dir.mkdir(parents=True)
    (process / "cmdline").write_bytes(b"/usr/local/bin/codex\0resume\0")
    (process / "comm").write_text("codex\n", encoding="utf-8")
    (process / "smaps_rollup").write_text(
        f"Pss: {pss_mib * 1024} kB\nSwapPss: 768000 kB\n",
        encoding="utf-8",
    )
    os.symlink(session, fd_dir / "7")


def test_pressure_report_maps_live_fds_to_session_and_memory(tmp_path, monkeypatch):
    module = _load_module(monkeypatch)
    home = tmp_path / ".codex-work"
    session = (
        home
        / "sessions"
        / "2026"
        / "08"
        / "01"
        / "rollout-2026-08-01T00-00-00-019fc000-0000-7000-8000-000000000000.jsonl"
    )
    session.parent.mkdir(parents=True)
    with session.open("wb") as handle:
        handle.truncate(600 * MIB)
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _active_proc(proc_root, 1234, session, pss_mib=3072)

    snapshot = module.collect_snapshot([home], proc_root=proc_root, now=1785715200)
    report = module.evaluate_snapshot(snapshot)

    assert report["status"] == "fail"
    assert report["sessions"][0]["active_pids"] == [1234]
    assert report["sessions"][0]["resume_blocked"] is True
    assert report["processes"][0]["pss_limit_exceeded"] is True
    assert report["kpis"]["oversized_active_session_count"] == 1
    assert report["kpis"]["codex_process_swap_pss_bytes"] == 768000 * 1024
    assert {issue["check"] for issue in report["issues"]} == {
        "active_session_size",
        "active_session_age",
        "codex_process_pss",
    }


def test_resume_check_blocks_large_direct_target_but_not_bare_picker(
    tmp_path, monkeypatch
):
    module = _load_module(monkeypatch)
    home = tmp_path / ".codex-work"
    sessions_root = home / "sessions" / "2026" / "08" / "01"
    sessions_root.mkdir(parents=True)
    large = (
        sessions_root
        / "rollout-2026-08-01T00-00-00-019fc000-0000-7000-8000-000000000000.jsonl"
    )
    small = (
        sessions_root
        / "rollout-2026-08-01T01-00-00-019fc001-0000-7000-8000-000000000000.jsonl"
    )
    with large.open("wb") as handle:
        handle.truncate(600 * MIB)
    small.write_text("{}\n", encoding="utf-8")
    os.utime(large, (100, 100))
    os.utime(small, (200, 200))
    report = module.evaluate_snapshot(
        module.collect_snapshot([home], proc_root=tmp_path / "missing", now=300)
    )

    direct = module.resume_decision(report, "019fc000")
    last = module.resume_decision(report, "last")
    bare = module.resume_decision(report, "")

    assert direct["action"] == "block"
    assert last["action"] == "allow"
    assert bare["action"] == "warn"


def test_cli_returns_distinct_exit_code_for_blocked_resume(tmp_path, monkeypatch):
    module = _load_module(monkeypatch)
    home = tmp_path / ".codex-work"
    session = (
        home
        / "sessions"
        / "2026"
        / "08"
        / "01"
        / "rollout-2026-08-01T00-00-00-019fc000-0000-7000-8000-000000000000.jsonl"
    )
    session.parent.mkdir(parents=True)
    with session.open("wb") as handle:
        handle.truncate(600 * MIB)

    assert (
        module.main(
            [
                "--codex-home",
                str(home),
                "--resume-target",
                "019fc000",
                "--no-write",
                "--quiet",
            ]
        )
        == 3
    )
