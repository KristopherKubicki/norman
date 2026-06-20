"""Screen-based hypervisor helpers for Norman runtime/session orchestration.

This module provides a small control plane around GNU screen:
- registry-backed app/session definitions
- lifecycle controls (up/down/status)
- per-target lock + inflight queue semantics
- incremental log ingestion for response pickup
"""

from __future__ import annotations

import json
import pathlib
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List

import yaml


_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = _ROOT / "db" / "hypervisor" / "apps.yaml"
DEFAULT_STATE_DIR = _ROOT / "db" / "hypervisor" / "state"
DEFAULT_LOG_DIR = _ROOT / "logs" / "hypervisor"

_SCREEN_SESSION_RE = re.compile(r"^\s*\d+\.([^\s]+)\s+\((Detached|Attached)\)\s*$")


class HypervisorError(RuntimeError):
    """Raised for invalid hypervisor state or runtime failures."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def screen_available() -> bool:
    return shutil.which("screen") is not None


def _run_screen(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    if not screen_available():
        raise HypervisorError("screen is not installed")
    proc = subprocess.run(
        ["screen", *args],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if check and proc.returncode != 0:
        raise HypervisorError(
            (proc.stderr or proc.stdout or "screen command failed").strip()
        )
    return proc


def _default_registry() -> Dict[str, Any]:
    return {"apps": {}}


def load_registry(path: str | pathlib.Path = DEFAULT_REGISTRY_PATH) -> Dict[str, Any]:
    registry_path = pathlib.Path(path).expanduser()
    if not registry_path.exists():
        raise HypervisorError(f"Registry not found: {registry_path}")
    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise HypervisorError(f"Failed to parse registry: {registry_path}") from exc
    if not isinstance(raw, dict):
        raise HypervisorError("Registry root must be a mapping")
    apps = raw.get("apps") or {}
    if not isinstance(apps, dict):
        raise HypervisorError("Registry `apps` must be a mapping")
    normalized = _default_registry()
    normalized["apps"] = apps
    return normalized


def init_registry(
    path: str | pathlib.Path = DEFAULT_REGISTRY_PATH,
    *,
    overwrite: bool = False,
) -> pathlib.Path:
    registry_path = pathlib.Path(path).expanduser()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    if registry_path.exists() and not overwrite:
        raise HypervisorError(f"Registry already exists: {registry_path}")
    template_path = _ROOT / "db" / "hypervisor" / "apps.yaml.dist"
    if template_path.exists():
        registry_path.write_text(
            template_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    else:
        registry_path.write_text("apps: {}\n", encoding="utf-8")
    return registry_path


def _app_entry(registry: Dict[str, Any], app_name: str) -> Dict[str, Any]:
    apps = registry.get("apps") or {}
    app = apps.get(app_name)
    if not isinstance(app, dict):
        raise HypervisorError(f"App not found in registry: {app_name}")
    return app


def _target_entry(app_entry: Dict[str, Any], target: str) -> Dict[str, Any]:
    value = app_entry.get(target)
    if not isinstance(value, dict):
        raise HypervisorError(f"Target `{target}` is not configured")
    return value


def _target_session_name(app_name: str, target: str, target_cfg: Dict[str, Any]) -> str:
    explicit = str(target_cfg.get("screen") or "").strip()
    if explicit:
        return explicit
    return f"{target}:{app_name}"


def _target_cwd(target_cfg: Dict[str, Any]) -> str:
    cwd = str(target_cfg.get("cwd") or "").strip()
    if not cwd:
        raise HypervisorError("Target missing `cwd`")
    return str(pathlib.Path(cwd).expanduser())


def _target_command(target_cfg: Dict[str, Any]) -> str:
    command = str(target_cfg.get("command") or "").strip()
    if not command:
        raise HypervisorError("Target missing `command`")
    return command


def _target_log_file(
    app_name: str,
    target: str,
    target_cfg: Dict[str, Any],
    *,
    log_dir: str | pathlib.Path = DEFAULT_LOG_DIR,
) -> pathlib.Path:
    explicit = str(target_cfg.get("log_file") or "").strip()
    if explicit:
        p = pathlib.Path(explicit).expanduser()
        if not p.is_absolute():
            p = _ROOT / p
        return p
    base = pathlib.Path(log_dir).expanduser()
    return base / f"{app_name}.{target}.log"


def list_screen_sessions() -> List[str]:
    proc = _run_screen("-ls")
    if proc.returncode != 0:
        return []
    sessions: List[str] = []
    for line in (proc.stdout or "").splitlines():
        match = _SCREEN_SESSION_RE.match(line.strip())
        if match:
            sessions.append(match.group(1))
    return sessions


def _session_exists(session_name: str) -> bool:
    return session_name in set(list_screen_sessions())


def _state_file(
    app_name: str,
    target: str,
    *,
    state_dir: str | pathlib.Path = DEFAULT_STATE_DIR,
) -> pathlib.Path:
    base = pathlib.Path(state_dir).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{app_name}.{target}.state.json"


def _queue_file(
    app_name: str,
    target: str,
    *,
    state_dir: str | pathlib.Path = DEFAULT_STATE_DIR,
) -> pathlib.Path:
    base = pathlib.Path(state_dir).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{app_name}.{target}.queue.jsonl"


def _default_state(
    app_name: str, target: str, state_dir: str | pathlib.Path
) -> Dict[str, Any]:
    return {
        "locked": False,
        "inflight": False,
        "log_offset": 0,
        "queue_file": str(_queue_file(app_name, target, state_dir=state_dir)),
        "updated_at": _utc_now_iso(),
    }


def load_state(
    app_name: str,
    target: str,
    *,
    state_dir: str | pathlib.Path = DEFAULT_STATE_DIR,
) -> Dict[str, Any]:
    path = _state_file(app_name, target, state_dir=state_dir)
    state = _default_state(app_name, target, state_dir)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        if isinstance(raw, dict):
            state.update(raw)
    return state


def save_state(
    app_name: str,
    target: str,
    state: Dict[str, Any],
    *,
    state_dir: str | pathlib.Path = DEFAULT_STATE_DIR,
) -> pathlib.Path:
    path = _state_file(app_name, target, state_dir=state_dir)
    state = dict(state)
    state["updated_at"] = _utc_now_iso()
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _append_queue(
    app_name: str,
    target: str,
    *,
    text: str,
    enter_count: int,
    state_dir: str | pathlib.Path = DEFAULT_STATE_DIR,
) -> int:
    queue_path = _queue_file(app_name, target, state_dir=state_dir)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "queued_at": _utc_now_iso(),
        "text": str(text),
        "enter_count": int(enter_count),
    }
    with queue_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return queue_length(app_name, target, state_dir=state_dir)


def queue_length(
    app_name: str,
    target: str,
    *,
    state_dir: str | pathlib.Path = DEFAULT_STATE_DIR,
) -> int:
    queue_path = _queue_file(app_name, target, state_dir=state_dir)
    if not queue_path.exists():
        return 0
    with queue_path.open("r", encoding="utf-8", errors="ignore") as handle:
        return sum(1 for _ in handle)


def _pop_queue(
    app_name: str,
    target: str,
    *,
    state_dir: str | pathlib.Path = DEFAULT_STATE_DIR,
) -> Dict[str, Any] | None:
    queue_path = _queue_file(app_name, target, state_dir=state_dir)
    if not queue_path.exists():
        return None
    lines = queue_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines:
        return None
    first = lines[0]
    rest = lines[1:]
    if rest:
        queue_path.write_text("\n".join(rest) + "\n", encoding="utf-8")
    else:
        queue_path.unlink(missing_ok=True)
    try:
        item = json.loads(first)
    except Exception:
        return None
    if not isinstance(item, dict):
        return None
    return item


def _dispatch_to_session(session_name: str, text: str, enter_count: int) -> None:
    payload = text + ("\r" * max(1, int(enter_count)))
    _run_screen("-S", session_name, "-p", "0", "-X", "stuff", payload, check=True)


def _targets_for(app_entry: Dict[str, Any], target: str) -> List[str]:
    if target == "both":
        return [
            name for name in ("app", "agent") if isinstance(app_entry.get(name), dict)
        ]
    if target not in {"app", "agent"}:
        raise HypervisorError("Target must be one of: app, agent, both")
    return [target]


def start_target(
    registry: Dict[str, Any],
    app_name: str,
    *,
    target: str,
    log_dir: str | pathlib.Path = DEFAULT_LOG_DIR,
) -> Dict[str, Any]:
    app = _app_entry(registry, app_name)
    cfg = _target_entry(app, target)
    session_name = _target_session_name(app_name, target, cfg)
    if _session_exists(session_name):
        return {"status": "already-running", "session": session_name}

    cwd = _target_cwd(cfg)
    command = _target_command(cfg)
    log_file = _target_log_file(app_name, target, cfg, log_dir=log_dir)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    launch_cmd = f"cd {shlex.quote(cwd)} && {command}"
    _run_screen(
        "-dmS",
        session_name,
        "-L",
        "-Logfile",
        str(log_file),
        "bash",
        "-lc",
        launch_cmd,
        check=True,
    )
    return {"status": "started", "session": session_name, "log_file": str(log_file)}


def stop_target(
    registry: Dict[str, Any],
    app_name: str,
    *,
    target: str,
) -> Dict[str, Any]:
    app = _app_entry(registry, app_name)
    cfg = _target_entry(app, target)
    session_name = _target_session_name(app_name, target, cfg)
    if not _session_exists(session_name):
        return {"status": "not-running", "session": session_name}
    _run_screen("-S", session_name, "-X", "quit")
    return {"status": "stopped", "session": session_name}


def send(
    registry: Dict[str, Any],
    app_name: str,
    *,
    text: str,
    target: str = "agent",
    enter_count: int = 2,
    state_dir: str | pathlib.Path = DEFAULT_STATE_DIR,
) -> Dict[str, Any]:
    app = _app_entry(registry, app_name)
    cfg = _target_entry(app, target)
    session_name = _target_session_name(app_name, target, cfg)
    state = load_state(app_name, target, state_dir=state_dir)
    is_locked = bool(state.get("locked"))
    is_inflight = bool(state.get("inflight"))

    if is_locked or is_inflight or not _session_exists(session_name):
        queued = _append_queue(
            app_name,
            target,
            text=text,
            enter_count=enter_count,
            state_dir=state_dir,
        )
        state["last_queued_at"] = _utc_now_iso()
        save_state(app_name, target, state, state_dir=state_dir)
        reason = (
            "locked" if is_locked else "inflight" if is_inflight else "session-down"
        )
        return {
            "status": "queued",
            "reason": reason,
            "target": target,
            "session": session_name,
            "queue_length": queued,
        }

    _dispatch_to_session(session_name, text, enter_count)
    state["inflight"] = True
    state["last_sent_at"] = _utc_now_iso()
    save_state(app_name, target, state, state_dir=state_dir)
    return {"status": "sent", "target": target, "session": session_name}


def drain_queue(
    registry: Dict[str, Any],
    app_name: str,
    *,
    target: str = "agent",
    state_dir: str | pathlib.Path = DEFAULT_STATE_DIR,
) -> Dict[str, Any]:
    app = _app_entry(registry, app_name)
    cfg = _target_entry(app, target)
    session_name = _target_session_name(app_name, target, cfg)
    state = load_state(app_name, target, state_dir=state_dir)

    if bool(state.get("locked")):
        return {"status": "blocked", "reason": "locked", "drained": 0}
    if bool(state.get("inflight")):
        return {"status": "blocked", "reason": "inflight", "drained": 0}
    if not _session_exists(session_name):
        return {"status": "blocked", "reason": "session-down", "drained": 0}

    item = _pop_queue(app_name, target, state_dir=state_dir)
    if not item:
        return {"status": "idle", "drained": 0}

    _dispatch_to_session(
        session_name,
        str(item.get("text") or ""),
        int(item.get("enter_count") or 2),
    )
    state["inflight"] = True
    state["last_sent_at"] = _utc_now_iso()
    save_state(app_name, target, state, state_dir=state_dir)
    return {
        "status": "drained",
        "drained": 1,
        "remaining": queue_length(app_name, target, state_dir=state_dir),
    }


def set_lock(
    registry: Dict[str, Any],
    app_name: str,
    *,
    target: str = "agent",
    locked: bool,
    state_dir: str | pathlib.Path = DEFAULT_STATE_DIR,
) -> Dict[str, Any]:
    _ = _target_entry(_app_entry(registry, app_name), target)
    state = load_state(app_name, target, state_dir=state_dir)
    state["locked"] = bool(locked)
    if locked:
        state["locked_at"] = _utc_now_iso()
    else:
        state["unlocked_at"] = _utc_now_iso()
    save_state(app_name, target, state, state_dir=state_dir)
    result = {"status": "locked" if locked else "unlocked", "target": target}
    if not locked:
        result["drain"] = drain_queue(
            registry, app_name, target=target, state_dir=state_dir
        )
    return result


def pull_logs(
    registry: Dict[str, Any],
    app_name: str,
    *,
    target: str = "agent",
    state_dir: str | pathlib.Path = DEFAULT_STATE_DIR,
    log_dir: str | pathlib.Path = DEFAULT_LOG_DIR,
    max_bytes: int = 65536,
    auto_ack: bool = True,
) -> Dict[str, Any]:
    app = _app_entry(registry, app_name)
    cfg = _target_entry(app, target)
    log_file = _target_log_file(app_name, target, cfg, log_dir=log_dir)
    state = load_state(app_name, target, state_dir=state_dir)
    offset = int(state.get("log_offset") or 0)
    if max_bytes < 1:
        max_bytes = 1
    if max_bytes > 1_000_000:
        max_bytes = 1_000_000

    text = ""
    if log_file.exists():
        with log_file.open("rb") as handle:
            handle.seek(0, 2)
            end = handle.tell()
            if offset < 0 or offset > end:
                offset = 0
            handle.seek(offset)
            blob = handle.read(max_bytes)
            offset = handle.tell()
            text = blob.decode("utf-8", errors="ignore")

    state["log_offset"] = offset
    acked = False
    drained: Dict[str, Any] | None = None
    if auto_ack and bool(state.get("inflight")) and text.strip():
        state["inflight"] = False
        state["last_acked_at"] = _utc_now_iso()
        acked = True

    save_state(app_name, target, state, state_dir=state_dir)

    if acked:
        drained = drain_queue(registry, app_name, target=target, state_dir=state_dir)

    return {
        "status": "ok",
        "target": target,
        "log_file": str(log_file),
        "offset": offset,
        "acked": acked,
        "drain": drained or {"status": "skipped", "drained": 0},
        "text": text,
    }


def status(
    registry: Dict[str, Any],
    *,
    app_name: str | None = None,
    state_dir: str | pathlib.Path = DEFAULT_STATE_DIR,
    log_dir: str | pathlib.Path = DEFAULT_LOG_DIR,
) -> Dict[str, Any]:
    apps = registry.get("apps") or {}
    selected = [app_name] if app_name else sorted(apps.keys())
    running = set(list_screen_sessions())
    items: List[Dict[str, Any]] = []

    for name in selected:
        app = _app_entry(registry, name)
        targets: Dict[str, Any] = {}
        for target in ("app", "agent"):
            if not isinstance(app.get(target), dict):
                continue
            cfg = _target_entry(app, target)
            session_name = _target_session_name(name, target, cfg)
            state_obj = load_state(name, target, state_dir=state_dir)
            targets[target] = {
                "session": session_name,
                "running": session_name in running,
                "locked": bool(state_obj.get("locked")),
                "inflight": bool(state_obj.get("inflight")),
                "queue_length": queue_length(name, target, state_dir=state_dir),
                "log_file": str(_target_log_file(name, target, cfg, log_dir=log_dir)),
            }
        items.append({"name": name, "targets": targets})

    return {"items": items, "count": len(items)}
