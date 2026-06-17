"""Startup reconciliation for tmux-backed project connectors.

This keeps project tmux connectors aligned with sibling repo `.session` files:
- infer `working_dir` for `tmux:<project>` connectors when missing
- sync `session_bootstrap` from the project's last non-empty `.session` line
- ensure the tmux session/pane exists
- launch the bootstrap command when the pane is not already running it
"""

from __future__ import annotations

import pathlib
import shlex
import shutil
import subprocess
from typing import Dict, Sequence

from sqlalchemy.orm import Session

from app.core.logging import setup_logger
from app.db.session import SessionLocal
from app.models.connectors import Connector

logger = setup_logger(__name__)


def _run_tmux(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
        check=check,
        stdin=subprocess.DEVNULL,
    )


def _default_projects_root() -> pathlib.Path:
    # /.../norman/app/services/tmux_reconciler.py -> /.../norman -> /.../
    return pathlib.Path(__file__).resolve().parents[3]


def _parse_project_name(connector_name: str) -> str:
    text = str(connector_name or "").strip()
    if text.startswith("tmux:"):
        return text.split(":", 1)[1].strip()
    return ""


def _read_last_session_line(project_dir: pathlib.Path) -> str:
    session_file = project_dir / ".session"
    if not session_file.exists():
        return ""
    try:
        lines = [
            line.strip()
            for line in session_file.read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines()
        ]
    except OSError:
        return ""
    lines = [line for line in lines if line]
    return lines[-1] if lines else ""


def _normalize_command(command: str) -> str:
    return " ".join(str(command or "").split())


def _pane_child_command(target: str) -> str:
    pid_proc = _run_tmux("display-message", "-p", "-t", target, "#{pane_pid}")
    pid = str(pid_proc.stdout or "").strip()
    if not pid.isdigit():
        return ""

    proc = subprocess.run(
        ["ps", "-o", "pid=,ppid=,cmd=", "--ppid", pid],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        return ""
    for line in (proc.stdout or "").splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return ""


def _tmux_has_session(session_name: str) -> bool:
    proc = _run_tmux("has-session", "-t", session_name)
    return proc.returncode == 0


def _tmux_target_exists(target: str) -> bool:
    proc = _run_tmux("display-message", "-p", "-t", target, "#{pane_id}")
    return proc.returncode == 0


def _ensure_tmux_session(session_name: str, working_dir: str) -> bool:
    if _tmux_has_session(session_name):
        return False
    _run_tmux("new-session", "-d", "-s", session_name, "-c", working_dir, check=True)
    return True


def _command_matches(child_cmd: str, expected_cmd: str) -> bool:
    child = _normalize_command(child_cmd).lower()
    expected = _normalize_command(expected_cmd).lower()
    if not child or not expected:
        return False
    return expected in child


def _launch_session_command(target: str, working_dir: str, command: str) -> None:
    # Stop existing foreground process (if any), then relaunch in the right cwd.
    _run_tmux("send-keys", "-t", target, "C-c")
    launch_line = f"cd {shlex.quote(working_dir)} && {command}"
    _run_tmux("send-keys", "-t", target, "-l", launch_line, check=True)
    _run_tmux("send-keys", "-t", target, "C-m", check=True)


def reconcile_tmux_connectors(
    db: Session,
    projects_root: str | pathlib.Path | None = None,
    connector_ids: Sequence[int] | None = None,
) -> Dict[str, int]:
    summary: Dict[str, int] = {
        "connectors_seen": 0,
        "connectors_updated": 0,
        "sessions_started": 0,
        "commands_started": 0,
        "commands_already_running": 0,
        "errors": 0,
        "skipped_tmux_unavailable": 0,
    }

    if shutil.which("tmux") is None:
        summary["skipped_tmux_unavailable"] = 1
        return summary

    root = pathlib.Path(projects_root or _default_projects_root()).resolve()
    query = db.query(Connector).filter(Connector.connector_type == "tmux")
    if connector_ids:
        query = query.filter(Connector.id.in_([int(cid) for cid in connector_ids]))
    connectors = query.order_by(Connector.id.asc()).all()

    changed = False

    for connector in connectors:
        summary["connectors_seen"] += 1
        config = dict(connector.config or {})
        dirty = False

        session_name = str(config.get("session") or "").strip()
        project_name = _parse_project_name(connector.name or "") or session_name
        target = str(config.get("target") or "").strip()

        if not session_name and project_name:
            session_name = project_name
            config["session"] = session_name
            dirty = True
        if not target and session_name:
            target = f"{session_name}:0.0"
            config["target"] = target
            dirty = True

        working_dir = str(config.get("working_dir") or "").strip()
        project_dir = pathlib.Path(working_dir) if working_dir else root / project_name
        if project_name and project_dir.is_dir():
            resolved_working_dir = str(project_dir.resolve())
            if working_dir != resolved_working_dir:
                config["working_dir"] = resolved_working_dir
                working_dir = resolved_working_dir
                dirty = True

        bootstrap_cmd = ""
        if project_name and working_dir and pathlib.Path(working_dir).is_dir():
            bootstrap_cmd = _read_last_session_line(pathlib.Path(working_dir))
            if bootstrap_cmd and config.get("session_bootstrap") != bootstrap_cmd:
                config["session_bootstrap"] = bootstrap_cmd
                dirty = True

        if dirty:
            connector.config = config
            changed = True
            summary["connectors_updated"] += 1

        # Runtime reconcile is only possible when all runtime pieces are present.
        if not (session_name and target and working_dir and bootstrap_cmd):
            continue

        try:
            started = _ensure_tmux_session(session_name, working_dir)
            if started:
                summary["sessions_started"] += 1

            if not _tmux_target_exists(target):
                target = f"{session_name}:0.0"
                if config.get("target") != target:
                    config["target"] = target
                    connector.config = config
                    changed = True
                    summary["connectors_updated"] += 1

            child_cmd = _pane_child_command(target)
            if _command_matches(child_cmd, bootstrap_cmd):
                summary["commands_already_running"] += 1
                continue

            _launch_session_command(target, working_dir, bootstrap_cmd)
            summary["commands_started"] += 1
        except Exception:
            summary["errors"] += 1
            logger.exception(
                "tmux reconcile failed for connector id=%s name=%s target=%s",
                connector.id,
                connector.name,
                target,
            )

    if changed:
        db.commit()
    else:
        db.rollback()

    return summary


def reconcile_tmux_connectors_for_startup(
    projects_root: str | pathlib.Path | None = None,
) -> Dict[str, int]:
    db = SessionLocal()
    try:
        return reconcile_tmux_connectors(db=db, projects_root=projects_root)
    finally:
        db.close()
