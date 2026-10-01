from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def _load_cleanup(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_tmp_workspace_cleanup",
        scripts_dir / "tui_tmp_workspace_cleanup.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_tmp_workspace_cleanup"] = module
    spec.loader.exec_module(module)
    return module


def _age(path: Path, *, now: float, hours: float) -> None:
    timestamp = now - (hours * 3600)
    os.utime(path, (timestamp, timestamp))


def test_cleanup_removes_only_expired_clean_workspace_and_test_db(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_cleanup(monkeypatch)
    now = 1_728_000_000.0
    clean_workspace = tmp_path / "dace-clean"
    clean_workspace.mkdir()
    (clean_workspace / "result.txt").write_text("done", encoding="utf-8")
    test_db = tmp_path / "norman_test_42.db"
    test_db.write_text("sqlite", encoding="utf-8")
    _age(clean_workspace, now=now, hours=49)
    _age(test_db, now=now, hours=25)

    monkeypatch.setattr(module, "_has_open_files", lambda path: (False, "no open"))
    monkeypatch.setattr(
        module, "_git_status", lambda path: (True, "clean git worktree")
    )

    payload = module.cleanup(tmp_path, apply=True, now=now)

    assert not clean_workspace.exists()
    assert not test_db.exists()
    assert len(payload["removed"]) == 2
    assert payload["errors"] == []


def test_cleanup_preserves_dirty_open_and_unknown_paths(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_cleanup(monkeypatch)
    now = 1_728_000_000.0
    dirty = tmp_path / "dace-dirty"
    open_workspace = tmp_path / "deepbrand-open"
    unknown = tmp_path / "tmp.unmanaged"
    for path in (dirty, open_workspace, unknown):
        path.mkdir()
        _age(path, now=now, hours=72)

    def open_files(path: Path):
        if path == open_workspace:
            return True, "workspace has open files"
        return False, "no open files"

    monkeypatch.setattr(module, "_has_open_files", open_files)
    monkeypatch.setattr(
        module,
        "_git_status",
        lambda path: (
            (True, "clean git worktree")
            if path == open_workspace
            else (False, "git worktree has uncommitted changes")
        ),
    )

    payload = module.cleanup(tmp_path, apply=True, now=now)

    assert dirty.exists()
    assert open_workspace.exists()
    assert unknown.exists()
    assert {item["reason"] for item in payload["preserved"]} == {
        "git worktree has uncommitted changes",
        "workspace has open files",
    }


def test_dirty_workspace_skips_open_file_scan(monkeypatch, tmp_path: Path) -> None:
    module = _load_cleanup(monkeypatch)
    workspace = tmp_path / "dace-dirty"
    workspace.mkdir()
    candidate = module.CleanupCandidate(
        path=workspace,
        kind="agent_workspace",
        age_hours=72,
    )
    monkeypatch.setattr(
        module,
        "_git_status",
        lambda path: (False, "git worktree has uncommitted changes"),
    )
    monkeypatch.setattr(
        module,
        "_has_open_files",
        lambda path: (_ for _ in ()).throw(AssertionError("must not be called")),
    )

    assert module.evaluate_candidate(candidate) == (
        False,
        "git worktree has uncommitted changes",
    )


def test_open_file_check_uses_direct_lookup_for_database(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_cleanup(monkeypatch)
    database = tmp_path / "norman_test_42.db"
    database.write_text("sqlite", encoding="utf-8")
    commands: list[list[str]] = []

    def run(command, **kwargs):
        commands.append(command)
        return module.subprocess.CompletedProcess(
            command,
            0,
            stdout="1234\n",
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", run)

    assert module._has_open_files(database) == (True, "workspace has open files")
    assert commands == [["lsof", "-t", "--", str(database)]]


def test_cleanup_systemd_timer_is_idle_and_explicitly_applies_cleanup() -> None:
    root = Path(__file__).resolve().parents[1]
    service = (
        root / "scripts" / "systemd" / "norman-tui-tmp-workspace-cleanup.service"
    ).read_text(encoding="utf-8")
    timer = (
        root / "scripts" / "systemd" / "norman-tui-tmp-workspace-cleanup.timer"
    ).read_text(encoding="utf-8")

    assert "scripts/tui_tmp_workspace_cleanup.py --apply" in service
    assert "IOSchedulingClass=idle" in service
    assert "User=root" in service
    assert "OnUnitActiveSec=1d" in timer
    assert "Persistent=true" in timer
