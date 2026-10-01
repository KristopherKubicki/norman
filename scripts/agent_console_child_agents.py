#!/usr/bin/env python3
"""Persistent, pool-neutral child agent orchestration for Norman web TUIs."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


MAX_ACTIVE_CHILDREN = 10
MAX_RESULT_CHARS = 1000
MAX_ARTIFACTS = 20
CHILD_STARTUP_GRACE_SECONDS = 120
ACTIVE_STATUSES = frozenset({"provisioning", "starting", "running", "cancelling"})
WRITE_MODES = frozenset({"read_only", "patch_only"})
RUNTIME_REQUEST = Callable[
    [str, str, dict[str, Any] | None, float | None], dict[str, Any]
]
SCOPED_SKILL_SOURCE_ROOTS = (
    Path.home() / ".codex-work" / "skills",
    Path.home() / ".codex-personal" / "skills",
)


class ChildAgentError(RuntimeError):
    """Base error for requests made through the child agent broker."""


class ChildAgentConflict(ChildAgentError):
    """The child-agent request conflicts with the active child set."""


class ChildAgentUnavailable(ChildAgentError):
    """The Norman console runtime cannot accept a child-agent launch."""


class ChildAgentNotFound(ChildAgentError):
    """The requested child agent has no persisted record."""


def _now() -> int:
    return int(time.time())


def _clean_text(value: Any, *, limit: int) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    return text[:limit]


def _safe_identifier(value: Any, fallback: str, *, limit: int = 64) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(value or "")).strip("-_.:")
    return (clean or fallback)[:limit]


def _is_pid_alive(pid: Any) -> bool:
    try:
        clean_pid = int(pid)
    except (TypeError, ValueError):
        return False
    if clean_pid <= 0:
        return False
    try:
        os.kill(clean_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_scoped_skill_source(path: Path) -> bool:
    try:
        resolved_path = path.resolve()
    except (OSError, RuntimeError):
        return False
    for source_root in SCOPED_SKILL_SOURCE_ROOTS:
        try:
            resolved_path.relative_to(source_root.resolve())
        except (OSError, RuntimeError, ValueError):
            continue
        return True
    return False


class ChildAgentBroker:
    """Own child agent lifecycle and runtime bookkeeping for one parent TUI."""

    def __init__(
        self,
        *,
        state_dir: str | Path,
        parent_session: str,
        parent_tmux_socket: str,
        parent_script_path: str | Path,
        worker_script_path: str | Path,
        codex_home: str | Path,
        token: str | Callable[[], str] = "",
        agent_name: str = "Norman",
        workdir: str | Path = ".",
        runtime_enabled: bool = False,
        runtime_request: RUNTIME_REQUEST | None = None,
    ) -> None:
        self.state_dir = Path(state_dir).expanduser()
        self.parent_session = _safe_identifier(
            parent_session, "norman-console", limit=96
        )
        self.parent_tmux_socket = _safe_identifier(
            parent_tmux_socket, self.parent_session, limit=96
        )
        self.parent_script_path = Path(parent_script_path).expanduser()
        self.worker_script_path = Path(worker_script_path).expanduser()
        self.codex_home = Path(codex_home).expanduser()
        self.token = token
        self.agent_name = _clean_text(agent_name, limit=120) or "Norman"
        self.workdir = Path(workdir).expanduser()
        self.runtime_enabled = bool(runtime_enabled)
        self.runtime_request = runtime_request
        self.registry_path = self.state_dir / "child_agents.json"
        self.lock_path = self.state_dir / "child_agents.lock"
        self.children_dir = self.state_dir / "children"

    def list_children(self) -> list[dict[str, Any]]:
        """Return persisted children after inexpensive dead-process reconciliation."""
        with self._locked_registry() as registry:
            changed = self._reconcile_registry(registry)
            if changed:
                registry["updated_at"] = _now()
            records = list(registry["children"])
        return [self._public_record(record) for record in records]

    def spawn(
        self, *, label: Any, objective: Any, write_mode: Any = "read_only"
    ) -> dict[str, Any]:
        """Create a runtime subtask and a freshly isolated child web process."""
        self._assert_not_child_process()
        clean_label = _clean_text(label, limit=120)
        clean_objective = _clean_text(objective, limit=12000)
        clean_mode = str(write_mode or "read_only").strip().lower()
        if not clean_label:
            clean_label = "Child agent"
        if not clean_objective:
            raise ChildAgentError("A child-agent objective is required.")
        if clean_mode not in WRITE_MODES:
            raise ChildAgentError("Child write mode is invalid.")
        if not self.runtime_enabled:
            raise ChildAgentUnavailable(
                "The Norman console runtime is unavailable for child delegation."
            )

        child_id = self._new_child_id()
        created_at = _now()
        child_state_dir = self.children_dir / child_id
        record: dict[str, Any] = {
            "id": child_id,
            "label": clean_label,
            "objective": clean_objective,
            "write_mode": clean_mode,
            "status": "provisioning",
            "created_at": created_at,
            "updated_at": created_at,
            "pid": 0,
            "pgid": 0,
            "port": 0,
            "url": "",
            "state_dir": str(child_state_dir),
            "codex_home": str(child_state_dir / "codex-home"),
            "session": f"{self.parent_session}-child-{child_id}",
            "tmux_socket": f"{self.parent_tmux_socket}-child-{child_id}",
            "runtime_job_id": "",
            "workstream_id": "",
            "result": "",
            "artifacts": [],
            "error": "",
            "retry_count": 0,
            "runtime_result_recorded_at": 0,
            "retry_of": "",
        }
        with self._locked_registry() as registry:
            self._reconcile_registry(registry)
            active_count = sum(
                1
                for item in registry["children"]
                if str(item.get("status") or "") in ACTIVE_STATUSES
            )
            if active_count >= MAX_ACTIVE_CHILDREN:
                raise ChildAgentConflict(
                    f"At most {MAX_ACTIVE_CHILDREN} child agents may be active."
                )
            registry["children"].append(record)
            registry["updated_at"] = _now()

        try:
            runtime_ids = self._create_runtime_delegation(record)
            record.update(runtime_ids)
            self._update_record(
                child_id,
                status="starting",
                runtime_job_id=record["runtime_job_id"],
                workstream_id=record["workstream_id"],
                updated_at=_now(),
            )
            self._prepare_child_dirs(record)
            port = self._allocate_port()
            process = self._start_child_process(record, port)
            child_url = f"http://127.0.0.1:{port}"
            self._update_record(
                child_id,
                pid=process.pid,
                pgid=process.pid,
                port=port,
                url=child_url,
                status="starting",
                updated_at=_now(),
            )
            self._wait_for_child_health(child_url)
            self._submit_child_objective(child_url, record)
        except ChildAgentError as exc:
            self._mark_launch_failed(child_id, str(exc))
            self._cancel_runtime_job(record, reason="child launch failed")
            raise
        except (OSError, TimeoutError, urllib_error.URLError) as exc:
            self._mark_launch_failed(child_id, str(exc))
            self._cancel_runtime_job(record, reason="child launch failed")
            raise ChildAgentUnavailable(
                f"Child agent could not start: {_clean_text(exc, limit=300)}"
            ) from exc
        except Exception as exc:
            self._mark_launch_failed(child_id, str(exc))
            self._cancel_runtime_job(record, reason="child launch failed")
            raise ChildAgentUnavailable(
                f"Child agent launch failed: {_clean_text(exc, limit=300)}"
            ) from exc

        stored = self._update_record(
            child_id,
            status="running",
            error="",
            updated_at=_now(),
        )
        return self._public_record(stored)

    def rename(self, child_id: Any, label: Any) -> dict[str, Any]:
        clean_label = _clean_text(label, limit=120)
        if not clean_label:
            raise ChildAgentError("A child-agent label is required.")
        record = self._update_record(
            self._child_id(child_id), label=clean_label, updated_at=_now()
        )
        return self._public_record(record)

    def collect(self, child_id: Any) -> dict[str, Any]:
        clean_child_id = self._child_id(child_id)
        record = self._record(clean_child_id)
        if not _is_pid_alive(record.get("pid")):
            with self._locked_registry() as registry:
                self._reconcile_registry(registry)
                record = self._required_record(registry, clean_child_id)
            return self._public_record(record)
        child_url = str(record.get("url") or "").rstrip("/")
        if not child_url:
            raise ChildAgentError("The child agent does not have a reachable web URL.")

        try:
            status_payload = self._child_json_request("GET", f"{child_url}/api/status")
            response_payload = self._child_json_request(
                "GET", f"{child_url}/api/last-response"
            )
        except (OSError, TimeoutError, urllib_error.URLError) as exc:
            record = self._update_record(
                clean_child_id,
                status="failed",
                error=f"Child agent status check failed: {_clean_text(exc, limit=300)}",
                updated_at=_now(),
            )
            self._record_runtime_result(record, status="failed")
            return self._public_record(record)

        response = _clean_text(response_payload.get("text"), limit=MAX_RESULT_CHARS)
        error = _clean_text(status_payload.get("last_error"), limit=1000)
        pending = bool(status_payload.get("pending"))
        snapshot_state = str(status_payload.get("state") or "").strip().lower()
        if error:
            child_status = "failed"
        elif pending or snapshot_state in {"running", "cancelling", "queued"}:
            child_status = "running"
        elif response and response not in {
            "[no response yet]",
            "[session unavailable]",
        }:
            child_status = "completed"
        else:
            child_status = str(record.get("status") or "running")

        artifacts = self._safe_artifacts(
            record,
            status_payload.get("artifacts"),
            response_payload.get("artifacts"),
        )
        record = self._update_record(
            clean_child_id,
            status=child_status,
            result=response,
            artifacts=artifacts,
            error=error,
            updated_at=_now(),
        )
        if child_status in {"completed", "failed"}:
            self._record_runtime_result(record, status=child_status)
            record = self._record(clean_child_id)
        return self._public_record(record)

    def cancel(self, child_id: Any) -> dict[str, Any]:
        clean_child_id = self._child_id(child_id)
        record = self._record(clean_child_id)
        self._cancel_runtime_job(record, reason="cancelled from parent web TUI")
        self._terminate_child_process(record)
        record = self._update_record(
            clean_child_id,
            status="cancelled",
            error="",
            updated_at=_now(),
        )
        return self._public_record(record)

    def retry(self, child_id: Any) -> dict[str, Any]:
        previous = self._record(self._child_id(child_id))
        if str(previous.get("status") or "") in ACTIVE_STATUSES:
            self.cancel(previous["id"])
            previous = self._record(previous["id"])
        replacement = self.spawn(
            label=str(previous.get("label") or "Child agent"),
            objective=str(previous.get("objective") or ""),
            write_mode=str(previous.get("write_mode") or "read_only"),
        )
        replacement = self._update_record(
            replacement["id"],
            retry_count=int(previous.get("retry_count") or 0) + 1,
            retry_of=str(previous.get("id") or ""),
            updated_at=_now(),
        )
        return self._public_record(replacement)

    def _assert_not_child_process(self) -> None:
        if (
            os.environ.get("NORMAN_CHILD_AGENT") == "1"
            or os.environ.get("NORMAN_CHILD_DEPTH", "0") != "0"
        ):
            raise ChildAgentConflict("Child agents cannot launch nested child agents.")

    def _new_child_id(self) -> str:
        return f"child-{uuid.uuid4().hex[:12]}"

    def _child_id(self, value: Any) -> str:
        child_id = _safe_identifier(value, "", limit=96)
        if not child_id:
            raise ChildAgentNotFound("Child agent not found.")
        return child_id

    def _registry_template(self) -> dict[str, Any]:
        return {"version": 1, "updated_at": _now(), "children": []}

    def _ensure_state_dir(self) -> None:
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self.state_dir.chmod(0o700)
        except OSError:
            pass
        self.children_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self.children_dir.chmod(0o700)
        except OSError:
            pass

    @contextlib.contextmanager
    def _locked_registry(self) -> Iterator[dict[str, Any]]:
        self._ensure_state_dir()
        with self.lock_path.open("a+", encoding="utf-8") as lock_file:
            try:
                self.lock_path.chmod(0o600)
            except OSError:
                pass
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            registry = self._load_registry()
            try:
                yield registry
            finally:
                self._write_registry(registry)
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _load_registry(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return self._registry_template()
        if not isinstance(payload, dict):
            return self._registry_template()
        children = payload.get("children")
        if not isinstance(children, list):
            payload["children"] = []
        payload.setdefault("version", 1)
        payload.setdefault("updated_at", _now())
        return payload

    def _write_registry(self, registry: dict[str, Any]) -> None:
        self._ensure_state_dir()
        encoded = json.dumps(registry, sort_keys=True, separators=(",", ":")) + "\n"
        temporary = self.registry_path.with_suffix(".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, self.registry_path)
        try:
            self.registry_path.chmod(0o600)
        except OSError:
            pass

    def _required_record(
        self, registry: dict[str, Any], child_id: str
    ) -> dict[str, Any]:
        for record in registry.get("children", []):
            if isinstance(record, dict) and record.get("id") == child_id:
                return record
        raise ChildAgentNotFound("Child agent not found.")

    def _record(self, child_id: str) -> dict[str, Any]:
        with self._locked_registry() as registry:
            record = dict(self._required_record(registry, child_id))
        return record

    def _update_record(self, child_id: str, **updates: Any) -> dict[str, Any]:
        with self._locked_registry() as registry:
            record = self._required_record(registry, child_id)
            record.update(updates)
            registry["updated_at"] = _now()
            return dict(record)

    def _reconcile_registry(self, registry: dict[str, Any]) -> bool:
        changed = False
        for record in registry.get("children", []):
            if not isinstance(record, dict):
                continue
            status = str(record.get("status") or "")
            if status not in ACTIVE_STATUSES:
                continue
            try:
                pid = int(record.get("pid") or 0)
            except (TypeError, ValueError):
                pid = 0
            if pid <= 0:
                # Reserve a launch slot until the parent finishes creating the
                # runtime subtask and records the child process PID.
                try:
                    updated_at = int(record.get("updated_at") or 0)
                except (TypeError, ValueError):
                    updated_at = 0
                age = max(0, _now() - updated_at)
                if (
                    status in {"provisioning", "starting"}
                    and age >= CHILD_STARTUP_GRACE_SECONDS
                ):
                    record["status"] = "failed"
                    record["updated_at"] = _now()
                    if not str(record.get("error") or "").strip():
                        record["error"] = "Child launch did not attach a web process."
                    changed = True
                continue
            if _is_pid_alive(pid):
                continue
            record["status"] = "stopped"
            record["updated_at"] = _now()
            if not str(record.get("error") or "").strip():
                record["error"] = "Child web process exited."
            changed = True
        return changed

    def _create_runtime_delegation(self, record: dict[str, Any]) -> dict[str, str]:
        child_id = str(record["id"])
        coordinator_id = f"{child_id}-coordinator"
        coordinator = self._runtime_json_request(
            "POST",
            "/console-runtime/jobs",
            {
                "job_id": coordinator_id,
                "objective": (
                    f"Coordinate child agent {record['label']} for {self.agent_name}."
                ),
                "done_when": ["The delegated child agent has returned a result."],
                "success_metrics": [
                    "The child agent result is available to the parent."
                ],
                "max_runtime_seconds": 7200,
                "checkpoint_interval_seconds": 900,
                "question_budget": 0,
                "route_policy": {},
                "metadata": {
                    "source": "agent_console_child_agents",
                    "kind": "child_agent_coordinator",
                    "parent_session": self.parent_session,
                    "child_id": child_id,
                },
            },
        )
        coordinator_job_id = (
            _clean_text(coordinator.get("job_id"), limit=128) or coordinator_id
        )
        workstream = self._runtime_json_request(
            "POST",
            "/console-runtime/workstreams",
            {
                "coordinator_job_id": coordinator_job_id,
                "workstream_id": f"{child_id}-workstream",
                "title": f"{self.agent_name}: {record['label']}",
                "metadata": {
                    "source": "agent_console_child_agents",
                    "parent_session": self.parent_session,
                    "child_id": child_id,
                },
                "max_concurrency": MAX_ACTIVE_CHILDREN,
            },
        )
        workstream_id = _clean_text(workstream.get("workstream_id"), limit=128)
        if not workstream_id:
            raise ChildAgentUnavailable(
                "The console runtime did not create a workstream."
            )
        delegated = self._runtime_json_request(
            "POST",
            f"/console-runtime/workstreams/{urllib_parse.quote(workstream_id, safe='')}/subtasks",
            {
                "subtasks": [
                    {
                        "job_id": child_id,
                        "title": str(record["label"]),
                        "objective": str(record["objective"]),
                        "done_when": ["Return a concise result to the parent TUI."],
                        "success_metrics": [
                            "The parent can collect the child result and artifacts."
                        ],
                        "max_runtime_seconds": 7200,
                        "checkpoint_interval_seconds": 900,
                        "question_budget": 0,
                        "route_policy": {},
                        "metadata": {
                            "source": "agent_console_child_agents",
                            "kind": "child_agent",
                            "parent_session": self.parent_session,
                            "child_id": child_id,
                        },
                        "write_mode": str(record["write_mode"]),
                    }
                ]
            },
        )
        items = delegated.get("items")
        item = items[0] if isinstance(items, list) and items else {}
        runtime_job_id = (
            _clean_text(item.get("job_id") if isinstance(item, dict) else "", limit=128)
            or child_id
        )
        return {"runtime_job_id": runtime_job_id, "workstream_id": workstream_id}

    def _resolve_token(self) -> str:
        value = self.token() if callable(self.token) else self.token
        return str(value or "").strip()

    def _runtime_json_request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self.runtime_enabled:
            raise ChildAgentUnavailable("The Norman console runtime is unavailable.")
        try:
            if self.runtime_request is not None:
                response = self.runtime_request(method, path, payload, 15.0)
            else:
                response = self._generic_runtime_json_request(method, path, payload)
        except (
            urllib_error.HTTPError,
            urllib_error.URLError,
            OSError,
            TimeoutError,
        ) as exc:
            raise ChildAgentUnavailable(
                f"Norllama-pool delegation failed: {_clean_text(exc, limit=300)}"
            ) from exc
        if not isinstance(response, dict):
            raise ChildAgentUnavailable(
                "The console runtime returned an invalid response."
            )
        return response

    def _generic_runtime_json_request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        base = (
            os.environ.get("NORMAN_CONSOLE_RUNTIME_API_BASE", "").strip()
            or os.environ.get("NORMAN_API_BASE_URL", "").strip()
        ).rstrip("/")
        if not base:
            raise ChildAgentUnavailable(
                "The Norman console runtime URL is not configured."
            )
        clean_path = "/" + str(path or "").lstrip("/")
        if base.endswith("/console-runtime"):
            if clean_path.startswith("/console-runtime/"):
                clean_path = clean_path[len("/console-runtime") :]
            elif clean_path == "/console-runtime":
                clean_path = ""
            url = f"{base}{clean_path}"
        elif base.endswith("/api/v1"):
            url = f"{base}{clean_path}"
        else:
            url = f"{base}/api/v1{clean_path}"
        body = (
            json.dumps(payload, sort_keys=True).encode("utf-8")
            if payload is not None
            else None
        )
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        token = self._resolve_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib_request.Request(url, data=body, headers=headers, method=method)
        with urllib_request.urlopen(request, timeout=15.0) as response:
            raw = response.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    def _prepare_child_dirs(self, record: dict[str, Any]) -> None:
        child_state_dir = Path(str(record["state_dir"]))
        child_state_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        child_state_dir.chmod(0o700)
        child_codex_home = Path(str(record["codex_home"]))
        child_codex_home.mkdir(mode=0o700, parents=True, exist_ok=True)
        child_codex_home.chmod(0o700)
        self._inherit_parent_scoped_skills(child_codex_home)

    def _inherit_parent_scoped_skills(self, child_codex_home: Path) -> None:
        """Give a child only the managed skills visible to its parent route."""
        parent_skills = self.codex_home / "skills"
        try:
            entries = sorted(parent_skills.iterdir(), key=lambda item: item.name)
        except FileNotFoundError:
            return
        except OSError:
            return

        child_skills = child_codex_home / "skills"
        for entry in entries:
            if not entry.is_symlink() or not _is_scoped_skill_source(entry):
                continue
            try:
                source = entry.resolve()
            except (OSError, RuntimeError):
                continue
            if not source.is_dir() or not (source / "SKILL.md").is_file():
                continue
            try:
                child_skills.mkdir(mode=0o700, exist_ok=True)
                (child_skills / entry.name).symlink_to(source, target_is_directory=True)
            except OSError:
                continue

    def _allocate_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _start_child_process(
        self, record: dict[str, Any], port: int
    ) -> subprocess.Popen[bytes]:
        if not self.worker_script_path.is_file():
            raise ChildAgentUnavailable(
                f"Child worker web script is unavailable: {self.worker_script_path}"
            )
        child_state_dir = Path(str(record["state_dir"]))
        logs_path = child_state_dir / "child-web.log"
        env = dict(os.environ)
        env.update(
            {
                "NORMAN_CHILD_AGENT": "1",
                "NORMAN_CHILD_AGENT_ID": str(record["id"]),
                "NORMAN_CHILD_PARENT_SESSION": self.parent_session,
                "NORMAN_CHILD_DEPTH": "1",
                "NORMAN_CHILD_AGENT_WRITE_MODE": str(record["write_mode"]),
                "NORMAN_CODEX_WEB_BIND": "127.0.0.1",
                "NORMAN_CODEX_WEB_PORT": str(port),
                "NORMAN_CODEX_WEB_STATE_DIR": str(child_state_dir),
                "NORMAN_CODEX_SESSION": str(record["session"]),
                "NORMAN_CODEX_TMUX_SOCKET": str(record["tmux_socket"]),
                "NORMAN_CODEX_DEFAULT_RUNTIME": "localllm",
                "NORMAN_CODEX_FORCE_DEFAULT_RUNTIME": "1",
                "NORMAN_CONSOLE_RUNTIME_ENABLED": "0",
                "CODEX_HOME": str(record["codex_home"]),
                "NORMAN_CODEX_HOME": str(record["codex_home"]),
            }
        )
        token = self._resolve_token()
        if token:
            env["NORMAN_CODEX_WEB_TOKEN"] = token
        else:
            env.pop("NORMAN_CODEX_WEB_TOKEN", None)
        working_directory = (
            self.workdir if self.workdir.is_dir() else self.parent_script_path.parent
        )
        log_handle = logs_path.open("ab", buffering=0)
        try:
            return subprocess.Popen(
                [sys.executable, str(self.worker_script_path)],
                cwd=str(working_directory),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log_handle.close()

    def _child_request_url(self, url: str) -> str:
        token = self._resolve_token()
        if not token:
            return url
        delimiter = "&" if "?" in url else "?"
        return f"{url}{delimiter}{urllib_parse.urlencode({'token': token})}"

    def _wait_for_child_health(self, child_url: str) -> None:
        deadline = time.monotonic() + 6.0
        last_error = ""
        while time.monotonic() < deadline:
            try:
                self._child_json_request("GET", f"{child_url}/healthz", raw=True)
                return
            except (OSError, TimeoutError, urllib_error.URLError) as exc:
                last_error = str(exc)
                time.sleep(0.1)
        raise ChildAgentUnavailable(
            f"Child web process did not become healthy: {_clean_text(last_error, limit=220)}"
        )

    def _child_json_request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        *,
        raw: bool = False,
    ) -> dict[str, Any]:
        body = (
            json.dumps(payload, sort_keys=True).encode("utf-8")
            if payload is not None
            else None
        )
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib_request.Request(
            self._child_request_url(url),
            data=body,
            headers=headers,
            method=method.upper(),
        )
        with urllib_request.urlopen(request, timeout=3.0) as response:
            body_text = response.read().decode("utf-8", errors="replace")
        if raw:
            return {}
        try:
            parsed = json.loads(body_text) if body_text else {}
        except json.JSONDecodeError:
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    def _submit_child_objective(self, child_url: str, record: dict[str, Any]) -> None:
        write_mode = str(record["write_mode"])
        mode_instruction = (
            "Inspect and analyze only. Do not alter files, services, or external systems."
            if write_mode == "read_only"
            else (
                "Only modify repository files necessary for this objective. "
                "Do not deploy, restart services, or perform external side effects."
            )
        )
        message = (
            f"Child agent lane: {record['label']}\n"
            f"Write mode: {write_mode}\n"
            f"{mode_instruction}\n\n"
            f"{record['objective']}"
        )
        self._child_json_request(
            "POST",
            f"{child_url}/api/ask",
            {
                "runtime": "localllm",
                "route_lock": True,
                "message": message,
            },
        )

    def _safe_artifacts(self, record: dict[str, Any], *values: Any) -> list[str]:
        allowed_roots = [
            Path(str(record.get("state_dir") or "")).resolve(),
            self.workdir.resolve(),
        ]
        artifacts: list[str] = []
        for value in values:
            if not isinstance(value, list):
                continue
            for raw_item in value:
                item = _clean_text(raw_item, limit=1024)
                if not item:
                    continue
                candidate = Path(item)
                if not candidate.is_absolute():
                    candidate = self.workdir / candidate
                try:
                    resolved = candidate.resolve()
                except OSError:
                    continue
                if not any(
                    resolved == root or root in resolved.parents
                    for root in allowed_roots
                ):
                    continue
                rendered = str(resolved)
                if rendered not in artifacts:
                    artifacts.append(rendered)
                if len(artifacts) >= MAX_ARTIFACTS:
                    return artifacts
        return artifacts

    def _record_runtime_result(self, record: dict[str, Any], *, status: str) -> None:
        if int(record.get("runtime_result_recorded_at") or 0):
            return
        runtime_job_id = str(record.get("runtime_job_id") or "").strip()
        if not runtime_job_id:
            return
        runtime_status = "done" if status == "completed" else "failed"
        try:
            self._runtime_json_request(
                "POST",
                f"/console-runtime/jobs/{urllib_parse.quote(runtime_job_id, safe='')}/result",
                {
                    "status": runtime_status,
                    "summary": _clean_text(
                        record.get("result"), limit=MAX_RESULT_CHARS
                    ),
                    "detail": _clean_text(record.get("error"), limit=1000),
                    "artifacts": list(record.get("artifacts") or [])[:MAX_ARTIFACTS],
                    "metadata": {
                        "source": "agent_console_child_agents",
                        "child_id": record.get("id"),
                        "status": status,
                    },
                },
            )
        except ChildAgentUnavailable:
            return
        self._update_record(
            str(record["id"]), runtime_result_recorded_at=_now(), updated_at=_now()
        )

    def _cancel_runtime_job(self, record: dict[str, Any], *, reason: str) -> None:
        runtime_job_id = str(record.get("runtime_job_id") or "").strip()
        if not runtime_job_id:
            return
        try:
            self._runtime_json_request(
                "POST",
                f"/console-runtime/jobs/{urllib_parse.quote(runtime_job_id, safe='')}/cancel",
                {"reason": _clean_text(reason, limit=500)},
            )
        except ChildAgentUnavailable:
            return

    def _terminate_child_process(self, record: dict[str, Any]) -> None:
        pid = record.get("pgid") or record.get("pid")
        try:
            clean_pid = int(pid)
        except (TypeError, ValueError):
            return
        if clean_pid <= 0 or not _is_pid_alive(clean_pid):
            return
        try:
            os.killpg(clean_pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except PermissionError:
            return

    def _mark_launch_failed(self, child_id: str, error: str) -> None:
        try:
            record = self._record(child_id)
        except ChildAgentNotFound:
            return
        self._terminate_child_process(record)
        self._update_record(
            child_id,
            status="failed",
            error=_clean_text(error, limit=1000),
            updated_at=_now(),
        )

    def _public_record(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(record.get("id") or ""),
            "label": _clean_text(record.get("label"), limit=120),
            "objective": _clean_text(record.get("objective"), limit=12000),
            "write_mode": str(record.get("write_mode") or "read_only"),
            "status": str(record.get("status") or "unknown"),
            "created_at": int(record.get("created_at") or 0),
            "updated_at": int(record.get("updated_at") or 0),
            "pid": int(record.get("pid") or 0),
            "port": int(record.get("port") or 0),
            "url": _clean_text(record.get("url"), limit=512),
            "state_dir": _clean_text(record.get("state_dir"), limit=1024),
            "codex_home": _clean_text(record.get("codex_home"), limit=1024),
            "session": _clean_text(record.get("session"), limit=160),
            "tmux_socket": _clean_text(record.get("tmux_socket"), limit=160),
            "runtime_job_id": _clean_text(record.get("runtime_job_id"), limit=128),
            "workstream_id": _clean_text(record.get("workstream_id"), limit=128),
            "result": _clean_text(record.get("result"), limit=MAX_RESULT_CHARS),
            "artifacts": list(record.get("artifacts") or [])[:MAX_ARTIFACTS],
            "error": _clean_text(record.get("error"), limit=1000),
            "retry_count": int(record.get("retry_count") or 0),
            "retry_of": _clean_text(record.get("retry_of"), limit=96),
        }
