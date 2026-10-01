"""Durable, ordered SMS turn processing for an agent-console BBS endpoint."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib import error, request
from urllib.parse import urlparse


ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
TERMINAL_STATES = frozenset({"completed", "failed"})


class SmsTurnError(ValueError):
    """Raised for a malformed or inconsistent durable SMS turn."""


def _credential_text(path_value: Any) -> str:
    path = Path(str(path_value or "").strip()).expanduser()
    if not str(path):
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def configured_callback_token() -> str:
    """Load the callback token without putting it in a turn payload or state file."""
    direct = os.environ.get("NORMAN_CODEX_SMS_CALLBACK_TOKEN", "").strip()
    if direct:
        return direct
    for name in (
        "NORMAN_CODEX_SMS_CALLBACK_TOKEN_FILE",
        "SMS_CALLBACK_TOKEN_FILE",
    ):
        token = _credential_text(os.environ.get(name))
        if token:
            return token
    credentials_directory = os.environ.get("CREDENTIALS_DIRECTORY", "").strip()
    if credentials_directory:
        return _credential_text(Path(credentials_directory) / "sms-callback-token")
    return ""


def _safe_id(value: Any, label: str) -> str:
    clean = str(value or "").strip()
    if not ID_RE.fullmatch(clean):
        raise SmsTurnError(f"invalid {label}")
    return clean


def _normalized_text(value: Any, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean[: max(1, int(limit))]


def _private_callback_url(value: Any) -> str:
    clean = str(value or "").strip()
    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SmsTurnError("callback_url must use http or https with a host")
    if parsed.username or parsed.password:
        raise SmsTurnError("callback_url must not include credentials")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost":
        return clean
    try:
        addresses = {
            ipaddress.ip_address(info[4][0])
            for info in socket.getaddrinfo(
                hostname, parsed.port or 80, type=socket.SOCK_STREAM
            )
        }
    except (OSError, ValueError) as exc:
        raise SmsTurnError("callback_url must resolve to a private address") from exc
    if not addresses or not all(
        address.is_loopback or address.is_private or address.is_link_local
        for address in addresses
    ):
        raise SmsTurnError("callback_url must resolve to a private address")
    return clean


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise SmsTurnError(f"could not read durable SMS state {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SmsTurnError(f"durable SMS state {path} is not an object")
    return payload


class SmsTurnProcessor:
    """Accept, serialize, execute, and callback durable SMS conversation turns.

    The executor receives ``(turn, bbs_thread_id)`` and returns a mapping with a
    response ``body``, optional replacement ``bbs_thread_id``, and optional
    boolean ``success``. Every terminal result is persisted before its callback.
    """

    def __init__(
        self,
        *,
        state_dir: Path,
        executor: Callable[[dict[str, Any], str], dict[str, Any]],
        max_response_chars: int = 1600,
        callback_retry_seconds: float = 5,
        callback_sender: Callable[[str, str, dict[str, Any]], None] | None = None,
        callback_token: str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.conversations_dir = self.state_dir / "conversations"
        self.executor = executor
        self.max_response_chars = max(1, int(max_response_chars))
        self.callback_retry_seconds = max(0.1, float(callback_retry_seconds))
        self.callback_sender = callback_sender or self._send_callback
        self.callback_token = (
            configured_callback_token() if callback_token is None else callback_token
        ).strip()
        self.clock = clock
        self._lock = threading.RLock()
        self._work_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self.conversations_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def start(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._stop.clear()
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="sms-turn-processor",
                daemon=True,
            )
            self._worker.start()

    def stop(self, timeout: float = 2) -> None:
        self._stop.set()
        self._wake.set()
        worker = self._worker
        if worker:
            worker.join(timeout=max(0, timeout))

    def submit(self, payload: dict[str, Any]) -> dict[str, str]:
        turn = self._validated_turn(payload)
        conversation_id = turn["conversation_id"]
        turn_id = turn["turn_id"]
        with self._lock:
            state = self._load_conversation(conversation_id)
            turns = self._turns(state)
            existing = next(
                (item for item in turns if str(item.get("turn_id") or "") == turn_id),
                None,
            )
            if existing:
                if not self._same_turn(existing, turn):
                    raise SmsTurnError("duplicate turn_id has different content")
                return {"conversation_id": conversation_id, "turn_id": turn_id}
            if any(
                int(item.get("sequence") or 0) == turn["sequence"] for item in turns
            ):
                raise SmsTurnError("sequence is already assigned to another turn")
            turns.append(turn)
            turns.sort(key=lambda item: int(item.get("sequence") or 0))
            state["updated_at"] = self._now()
            self._write_conversation(state)
        self._wake.set()
        return {"conversation_id": conversation_id, "turn_id": turn_id}

    def process_pending(self) -> None:
        """Run eligible executions and due callbacks once; useful for tests."""
        if not self._work_lock.acquire(blocking=False):
            return
        try:
            for path in sorted(self.conversations_dir.glob("*.json")):
                self._process_conversation(path)
            for path in sorted(self.conversations_dir.glob("*.json")):
                self._flush_callbacks(path)
        finally:
            self._work_lock.release()

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.process_pending()
            except Exception:
                # Per-turn failures are made terminal below. This guards a damaged
                # state file without allowing a background worker crash to lose
                # unrelated conversations.
                pass
            self._wake.wait(self.callback_retry_seconds)
            self._wake.clear()

    def _validated_turn(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise SmsTurnError("SMS turn payload must be an object")
        conversation_id = _safe_id(payload.get("conversation_id"), "conversation_id")
        turn_id = _safe_id(payload.get("turn_id"), "turn_id")
        try:
            sequence = int(payload.get("sequence") or 0)
        except (TypeError, ValueError) as exc:
            raise SmsTurnError("sequence must be a positive integer") from exc
        if sequence <= 0:
            raise SmsTurnError("sequence must be a positive integer")
        message = _normalized_text(payload.get("message"), 16_000)
        if not message:
            raise SmsTurnError("message is required")
        legacy_callback_token = str(payload.get("callback_token") or "").strip()
        if not self.callback_token and not legacy_callback_token:
            raise SmsTurnError("callback_token is required")
        source = payload.get("source")
        if source is None:
            source = {}
        if not isinstance(source, dict):
            raise SmsTurnError("source must be an object")
        now = self._now()
        turn = {
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "sequence": sequence,
            "message": message,
            "callback_url": _private_callback_url(payload.get("callback_url")),
            "source": source,
            "status": "accepted",
            "accepted_at": now,
            "updated_at": now,
            "attempts": 0,
        }
        # Legacy per-turn tokens are supported only when no host credential is
        # configured. The configured service credential must never be persisted.
        if not self.callback_token:
            turn["callback_token"] = legacy_callback_token
        return turn

    def _conversation_path(self, conversation_id: str) -> Path:
        return (
            self.conversations_dir
            / f"{_safe_id(conversation_id, 'conversation_id')}.json"
        )

    def _load_conversation(self, conversation_id: str) -> dict[str, Any]:
        path = self._conversation_path(conversation_id)
        state = _read_json(path)
        if state is None:
            return {
                "schema_version": 1,
                "conversation_id": conversation_id,
                "turns": [],
                "created_at": self._now(),
                "updated_at": self._now(),
            }
        if str(state.get("conversation_id") or "") != conversation_id:
            raise SmsTurnError("durable SMS conversation correlation mismatch")
        self._turns(state)
        return state

    @staticmethod
    def _turns(state: dict[str, Any]) -> list[dict[str, Any]]:
        turns = state.setdefault("turns", [])
        if not isinstance(turns, list) or not all(
            isinstance(item, dict) for item in turns
        ):
            raise SmsTurnError("durable SMS turns are malformed")
        return turns

    def _write_conversation(self, state: dict[str, Any]) -> None:
        conversation_id = _safe_id(state.get("conversation_id"), "conversation_id")
        _atomic_write_json(self._conversation_path(conversation_id), state)

    def _same_turn(self, existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
        keys = (
            "turn_id",
            "sequence",
            "message",
            "callback_url",
            "source",
        )
        if not self.callback_token:
            keys = (*keys, "callback_token")
        return all(existing.get(key) == incoming.get(key) for key in keys)

    def _process_conversation(self, path: Path) -> None:
        conversation_id = path.stem
        with self._lock:
            state = self._load_conversation(conversation_id)
            turns = sorted(self._turns(state), key=lambda item: int(item["sequence"]))
            selected: dict[str, Any] | None = None
            expected_sequence = 1
            for turn in turns:
                sequence = int(turn.get("sequence") or 0)
                if sequence != expected_sequence:
                    # A future turn cannot run while durable state is missing an
                    # earlier sequence. The cloud producer always starts at one.
                    return
                status = str(turn.get("status") or "")
                if status in {"accepted", "running"}:
                    selected = dict(turn)
                    break
                if status not in TERMINAL_STATES:
                    return
                expected_sequence += 1
            if selected is None:
                return
            durable = self._find_turn(state, selected["turn_id"])
            durable["status"] = "running"
            durable["started_at"] = durable.get("started_at") or self._now()
            durable["attempts"] = int(durable.get("attempts") or 0) + 1
            durable["updated_at"] = self._now()
            state["updated_at"] = self._now()
            self._write_conversation(state)

        self._execute_turn(conversation_id, selected["turn_id"])

    def _execute_turn(self, conversation_id: str, turn_id: str) -> None:
        with self._lock:
            state = self._load_conversation(conversation_id)
            turn = dict(self._find_turn(state, turn_id))
            bbs_thread_id = str(
                turn.get("bbs_thread_id") or state.get("bbs_thread_id") or ""
            )
        try:
            result = self.executor(turn, bbs_thread_id)
            if not isinstance(result, dict):
                raise RuntimeError("SMS executor returned a non-object result")
            success = bool(result.get("success", True))
            body = _normalized_text(result.get("body"), self.max_response_chars)
            if not body:
                body = (
                    "I couldn't complete that text. Please try again."
                    if not success
                    else "I couldn't generate a reply. Please try again."
                )
            next_thread_id = str(result.get("bbs_thread_id") or bbs_thread_id).strip()
            if success and not next_thread_id:
                raise RuntimeError("SMS executor did not return a Codex thread id")
            terminal = "completed" if success else "failed"
            error_text = ""
        except Exception:
            success = False
            terminal = "failed"
            body = "I couldn't complete that text. Please try again."
            next_thread_id = bbs_thread_id
            error_text = "executor failed"

        with self._lock:
            state = self._load_conversation(conversation_id)
            durable = self._find_turn(state, turn_id)
            if str(durable.get("status") or "") in TERMINAL_STATES:
                return
            now = self._now()
            durable.update(
                {
                    "status": terminal,
                    "bbs_thread_id": next_thread_id,
                    "finished_at": now,
                    "updated_at": now,
                    "completion": {
                        "schema_version": 1,
                        "conversation_id": conversation_id,
                        "turn_id": turn_id,
                        "sequence": int(durable["sequence"]),
                        "status": terminal,
                        "success": success,
                        "body": body,
                        "bbs_thread_id": next_thread_id,
                        "started_at": int(durable.get("started_at") or now),
                        "finished_at": now,
                    },
                    "callback_status": "pending",
                    "callback_attempts": 0,
                    "callback_next_at": now,
                    "callback_error": error_text,
                }
            )
            if next_thread_id:
                state["bbs_thread_id"] = next_thread_id
            state["updated_at"] = now
            self._write_conversation(state)

    def _flush_callbacks(self, path: Path) -> None:
        conversation_id = path.stem
        with self._lock:
            state = self._load_conversation(conversation_id)
            candidates: list[dict[str, Any]] = []
            for turn in sorted(
                self._turns(state), key=lambda item: int(item["sequence"])
            ):
                if str(turn.get("status") or "") not in TERMINAL_STATES:
                    break
                if str(turn.get("callback_status") or "pending") == "sent":
                    continue
                if float(turn.get("callback_next_at") or 0) <= self.clock():
                    candidates.append(dict(turn))
                # Do not send later replies while this sequence is pending or
                # backing off. The cloud queues can then observe callbacks in
                # the same order as the serialized Codex execution.
                break
        for turn in candidates:
            self._deliver_callback(conversation_id, str(turn["turn_id"]))

    def _deliver_callback(self, conversation_id: str, turn_id: str) -> None:
        with self._lock:
            state = self._load_conversation(conversation_id)
            turn = dict(self._find_turn(state, turn_id))
            completion = turn.get("completion")
            if not isinstance(completion, dict):
                return
        try:
            token = self.callback_token or str(turn.get("callback_token") or "").strip()
            if not token:
                raise SmsTurnError("callback token is unavailable")
            self.callback_sender(
                str(turn["callback_url"]),
                token,
                completion,
            )
        except Exception:
            with self._lock:
                state = self._load_conversation(conversation_id)
                durable = self._find_turn(state, turn_id)
                attempts = int(durable.get("callback_attempts") or 0) + 1
                durable.update(
                    {
                        "callback_status": "pending",
                        "callback_attempts": attempts,
                        "callback_next_at": self._now() + self.callback_retry_seconds,
                        "callback_error": "callback delivery failed",
                    }
                )
                state["updated_at"] = self._now()
                self._write_conversation(state)
            return
        with self._lock:
            state = self._load_conversation(conversation_id)
            durable = self._find_turn(state, turn_id)
            durable.update(
                {
                    "callback_status": "sent",
                    "callback_attempts": int(durable.get("callback_attempts") or 0) + 1,
                    "callback_sent_at": self._now(),
                    "callback_error": "",
                }
            )
            state["updated_at"] = self._now()
            self._write_conversation(state)

    @staticmethod
    def _send_callback(url: str, token: str, completion: dict[str, Any]) -> None:
        encoded = json.dumps(completion, separators=(",", ":")).encode("utf-8")
        req = request.Request(
            url,
            data=encoded,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=15) as response:
                response.read()
                if not 200 <= int(response.status) < 300:
                    raise RuntimeError(f"callback returned {response.status}")
        except error.HTTPError as exc:
            raise RuntimeError(f"callback returned {exc.code}") from exc

    @staticmethod
    def _find_turn(state: dict[str, Any], turn_id: str) -> dict[str, Any]:
        for turn in SmsTurnProcessor._turns(state):
            if str(turn.get("turn_id") or "") == turn_id:
                return turn
        raise SmsTurnError("durable SMS turn was not found")

    def _now(self) -> int:
        return int(self.clock())
