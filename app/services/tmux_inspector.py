"""Read-only tmux inspection helpers.

These helpers are used for "console observability" features: listing running
tmux sessions/panes and capturing recent output for display in the UI.

Safety notes:
- Commands are executed without a shell (argv list), so user-provided targets
  cannot inject extra tmux commands.
- This module intentionally exposes *read-only* tmux operations only.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from typing import Any, Dict, List

_LAST_WORKING_SOCKET = ""


def _tmux_base_cmd(socket_path: str = "") -> list[str]:
    cmd = ["tmux"]
    if socket_path:
        cmd.extend(["-S", socket_path])
    return cmd


def tmux_available() -> bool:
    return shutil.which("tmux") is not None


def _normalize_socket_path(value: str) -> str:
    return str(value or "").strip()


def _discover_socket_paths() -> list[str]:
    candidates: list[str] = []
    uid = os.getuid()
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "")
    for base in (f"/tmp/tmux-{uid}", f"{runtime_dir}/tmux" if runtime_dir else ""):
        if not base or not os.path.isdir(base):
            continue
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for name in names:
            path = os.path.join(base, name)
            try:
                mode = os.stat(path).st_mode
            except OSError:
                continue
            if stat.S_ISSOCK(mode):
                candidates.append(path)
    return candidates


def _socket_attempts(socket_path: str = "") -> list[str]:
    requested = _normalize_socket_path(socket_path)
    if requested:
        return [requested]

    attempts = [""]
    seen = {""}

    for candidate in (
        _LAST_WORKING_SOCKET,
        os.environ.get("TMUX_SOCKET_PATH", ""),
        (os.environ.get("TMUX", "").split(",", 1)[0] if os.environ.get("TMUX") else ""),
    ):
        normalized = _normalize_socket_path(candidate)
        if normalized and normalized not in seen:
            attempts.append(normalized)
            seen.add(normalized)

    for discovered in _discover_socket_paths():
        normalized = _normalize_socket_path(discovered)
        if normalized and normalized not in seen:
            attempts.append(normalized)
            seen.add(normalized)

    return attempts


def _run_tmux(
    *args: str, socket_path: str = "", check: bool = False
) -> subprocess.CompletedProcess[str]:
    global _LAST_WORKING_SOCKET

    if not tmux_available():
        raise RuntimeError("tmux is not installed")

    last_proc: subprocess.CompletedProcess[str] | None = None
    last_cmd: list[str] | None = None

    for candidate in _socket_attempts(socket_path):
        cmd = [*_tmux_base_cmd(candidate), *args]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )
        last_proc = proc
        last_cmd = cmd
        if proc.returncode == 0:
            if candidate:
                _LAST_WORKING_SOCKET = candidate
            return proc

    if check and last_proc and last_cmd:
        raise subprocess.CalledProcessError(
            returncode=last_proc.returncode,
            cmd=last_cmd,
            output=last_proc.stdout,
            stderr=last_proc.stderr,
        )

    if last_proc is not None:
        return last_proc

    cmd = [*_tmux_base_cmd(socket_path), *args]
    return subprocess.CompletedProcess(
        cmd, returncode=1, stdout="", stderr="tmux failed"
    )


def list_sessions(*, socket_path: str = "") -> List[Dict[str, Any]]:
    """Return tmux sessions visible to this process.

    Returns an empty list if no tmux server is running.
    """

    fmt = "#{session_name}\t#{session_windows}\t#{session_attached}\t#{session_created_string}"
    try:
        proc = _run_tmux("list-sessions", "-F", fmt, socket_path=socket_path)
    except RuntimeError:
        return []
    if proc.returncode != 0:
        # Typical stderr: "no server running on /tmp/tmux-UID/default"
        return []

    items: List[Dict[str, Any]] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        name, windows_s, attached_s, created = parts[:4]
        try:
            windows = int(windows_s)
        except Exception:
            windows = 0
        try:
            attached = int(attached_s)
        except Exception:
            attached = 0
        items.append(
            {
                "session_name": name,
                "windows": windows,
                "attached": attached,
                "created": created,
            }
        )
    return items


def list_panes(*, socket_path: str = "") -> List[Dict[str, Any]]:
    """Return all panes across all sessions/windows."""

    fmt = (
        "#{session_name}\t#{window_index}\t#{window_name}\t#{pane_index}\t#{pane_id}\t"
        "#{pane_active}\t#{pane_current_command}\t#{pane_title}\t#{pane_tty}\t"
        "#{pane_width}\t#{pane_height}\t#{pane_current_path}"
    )
    try:
        proc = _run_tmux("list-panes", "-a", "-F", fmt, socket_path=socket_path)
    except RuntimeError:
        return []
    if proc.returncode != 0:
        return []

    items: List[Dict[str, Any]] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        (
            session_name,
            window_index_s,
            window_name,
            pane_index_s,
            pane_id,
            pane_active_s,
            pane_current_command,
            pane_title,
            pane_tty,
            pane_width_s,
            pane_height_s,
            pane_current_path,
        ) = parts[:12]

        try:
            window_index = int(window_index_s)
        except Exception:
            window_index = 0
        try:
            pane_index = int(pane_index_s)
        except Exception:
            pane_index = 0
        pane_active = str(pane_active_s).strip() == "1"
        try:
            pane_width = int(pane_width_s)
        except Exception:
            pane_width = 0
        try:
            pane_height = int(pane_height_s)
        except Exception:
            pane_height = 0

        target = f"{session_name}:{window_index}.{pane_index}"

        items.append(
            {
                "target": target,
                "session_name": session_name,
                "window_index": window_index,
                "window_name": window_name,
                "pane_index": pane_index,
                "pane_id": pane_id,
                "pane_active": pane_active,
                "pane_current_command": pane_current_command,
                "pane_title": pane_title,
                "pane_tty": pane_tty,
                "pane_width": pane_width,
                "pane_height": pane_height,
                "pane_current_path": pane_current_path,
            }
        )
    return items


def capture_pane(
    *,
    target: str,
    lines: int = 200,
    socket_path: str = "",
) -> str:
    """Capture the most recent ``lines`` from a tmux pane."""

    if not isinstance(target, str) or not target.strip():
        raise RuntimeError("Missing tmux target")

    # Keep responses bounded for UI + logs.
    if lines < 1:
        lines = 1
    if lines > 2000:
        lines = 2000

    proc = _run_tmux(
        "capture-pane",
        "-p",
        "-J",
        "-t",
        target.strip(),
        "-S",
        f"-{lines}",
        socket_path=socket_path,
        check=False,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or "").strip() or "tmux capture failed"
        raise RuntimeError(msg)
    return proc.stdout or ""
