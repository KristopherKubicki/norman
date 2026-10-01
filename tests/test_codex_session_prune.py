from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def _load_module(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "codex_session_prune", scripts_dir / "codex_session_prune.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["codex_session_prune"] = module
    spec.loader.exec_module(module)
    return module


def _session(home: Path, day: str, name: str, *, mtime: int) -> Path:
    path = home / "sessions" / "2026" / "07" / day / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("history\n", encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def test_prune_never_removes_active_files_and_preserves_retention_floor(
    tmp_path, monkeypatch
):
    module = _load_module(monkeypatch)
    home = tmp_path / ".codex-work"
    active = _session(home, "01", "active.jsonl", mtime=100)
    retained = _session(home, "02", "retained.jsonl", mtime=200)
    stale = _session(home, "03", "stale.jsonl", mtime=50)

    report = module.prune_sessions(
        [home],
        retention_days=1,
        retain_count=1,
        active_paths={active},
        now=500000,
    )

    assert active.exists()
    assert retained.exists()
    assert not stale.exists()
    assert report["removed_count"] == 1
    assert str(active) in report["skipped_active"]
    assert str(retained) in report["skipped_retention_floor"]


def test_prune_dry_run_reports_reclaim_without_deleting(tmp_path, monkeypatch):
    module = _load_module(monkeypatch)
    home = tmp_path / ".codex"
    stale = _session(home, "01", "stale.jsonl", mtime=100)

    report = module.prune_sessions(
        [home],
        retention_days=1,
        retain_count=0,
        active_paths=set(),
        now=500000,
        dry_run=True,
    )

    assert stale.exists()
    assert report["status"] == "dry_run"
    assert report["removed_count"] == 1


def test_active_session_paths_excludes_open_files_from_pruning(tmp_path, monkeypatch):
    module = _load_module(monkeypatch)
    home = tmp_path / ".codex-work"
    session = _session(home, "01", "open.jsonl", mtime=100)
    proc_root = tmp_path / "proc"
    fd_dir = proc_root / "4567" / "fd"
    fd_dir.mkdir(parents=True)
    os.symlink(session, fd_dir / "9")

    active = module.active_session_paths([home], proc_root=proc_root)
    report = module.prune_sessions(
        [home],
        retention_days=1,
        retain_count=0,
        active_paths=active,
        now=500000,
    )

    assert active == {session}
    assert session.exists()
    assert report["removed_count"] == 0
    assert str(session) in report["skipped_active"]
