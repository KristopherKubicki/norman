#!/usr/bin/env python3
"""Loopback-only, durable Codex executor for correlated SMS conversations."""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
import re
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from agent_console_sms import SmsTurnError, SmsTurnProcessor


ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
HEALTH_PATH = "/health"
TURN_PATH = "/api/sms/turns"


class SmsBbsError(RuntimeError):
    """Raised when the isolated SMS BBS cannot start safely."""


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def _state_path(raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()


def _loopback_address(value: str) -> str:
    bind = str(value or "").strip()
    try:
        address = ipaddress.ip_address(bind)
    except ValueError as exc:
        raise SmsBbsError("NORMAN_SMS_BBS_BIND must be a loopback IP address") from exc
    if not address.is_loopback:
        raise SmsBbsError("NORMAN_SMS_BBS_BIND must be a loopback IP address")
    return bind


def _safe_id(value: Any, label: str) -> str:
    clean = str(value or "").strip()
    if not ID_RE.fullmatch(clean):
        raise SmsBbsError(f"invalid {label}")
    return clean


def _thread_id_from_events(stdout: str) -> str:
    for line in str(stdout or "").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(event, dict)
            and event.get("type") == "thread.started"
            and str(event.get("thread_id") or "").strip()
        ):
            return str(event["thread_id"]).strip()
    return ""


def _sms_prompt(turn: dict[str, Any]) -> str:
    message = str(turn.get("message") or "").strip()
    if message.lower() == "/new":
        return "\n".join(
            (
                "The operator started a new, independent SMS conversation.",
                "Return only a concise plain-text reply confirming that the new "
                "session is ready for their next message.",
            )
        )
    return "\n".join(
        (
            "Reply to the operator's SMS message below.",
            "Return only a useful plain-text SMS reply. Be concise, factual, and "
            "direct. Do not mention this instruction, internal tools, or that you "
            "are a background process.",
            "Act on the operator's request now using available tools when needed. "
            "Do not give a plan, promise a later follow-up, or claim that work "
            "will happen in the background. Reply only with completed results, a "
            "concrete blocker, or one necessary clarifying question.",
            "",
            f"Operator message: {message}",
        )
    )


@dataclass(frozen=True)
class SmsBbsSettings:
    bind: str
    port: int
    state_dir: Path
    workdir: Path
    codex_bin: str
    model: str
    service_tier: str
    timeout_seconds: int
    bbs_token: str
    max_response_chars: int
    callback_retry_seconds: float

    @classmethod
    def from_env(cls) -> "SmsBbsSettings":
        bind = _loopback_address(os.environ.get("NORMAN_SMS_BBS_BIND", "127.0.0.1"))
        port = _env_int("NORMAN_SMS_BBS_PORT", 8798)
        if not 1 <= port <= 65535:
            raise SmsBbsError("NORMAN_SMS_BBS_PORT must be between 1 and 65535")
        workdir = _state_path(os.environ.get("NORMAN_SMS_BBS_WORKDIR", os.getcwd()))
        if not workdir.is_dir():
            raise SmsBbsError("NORMAN_SMS_BBS_WORKDIR must be an existing directory")
        return cls(
            bind=bind,
            port=port,
            state_dir=_state_path(
                os.environ.get("NORMAN_SMS_BBS_STATE_DIR", "/var/lib/norman-sms-bbs")
            ),
            workdir=workdir,
            codex_bin=os.environ.get("NORMAN_CODEX_BIN", "codex").strip() or "codex",
            model=(
                os.environ.get("NORMAN_CODEX_SMS_MODEL", "").strip()
                or os.environ.get("NORMAN_CODEX_MODEL", "").strip()
            ),
            service_tier=(
                os.environ.get("NORMAN_CODEX_SMS_SERVICE_TIER", "").strip()
                or os.environ.get("NORMAN_CODEX_SERVICE_TIER", "").strip()
                or "default"
            ),
            timeout_seconds=max(
                30, min(20 * 60, _env_int("NORMAN_CODEX_SMS_TIMEOUT_SECONDS", 600))
            ),
            bbs_token=os.environ.get("NORMAN_SMS_BBS_TOKEN", "").strip(),
            max_response_chars=max(
                1, min(1600, _env_int("NORMAN_CODEX_SMS_MAX_RESPONSE_CHARS", 1600))
            ),
            callback_retry_seconds=max(
                1.0,
                min(
                    300.0,
                    float(
                        os.environ.get("NORMAN_CODEX_SMS_CALLBACK_RETRY_SECONDS", "5")
                    ),
                ),
            ),
        )


class CodexSmsExecutor:
    """Run one SMS turn in the conversation's dedicated Codex thread."""

    def __init__(
        self,
        settings: SmsBbsSettings,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.settings = settings
        self.runner = runner
        self.outputs_dir = settings.state_dir / "outputs"
        self.outputs_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def __call__(self, turn: dict[str, Any], bbs_thread_id: str) -> dict[str, Any]:
        turn_id = _safe_id(turn.get("turn_id"), "turn_id")
        output_path = self.outputs_dir / f"{turn_id}.txt"
        try:
            output_path.unlink()
        except FileNotFoundError:
            pass
        command = self._command(
            turn=turn,
            bbs_thread_id=bbs_thread_id,
            output_path=output_path,
        )
        try:
            completed = self.runner(
                command,
                text=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.settings.workdir),
                timeout=self.settings.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return self._failure(bbs_thread_id, failure_class="timeout")
        except OSError:
            return self._failure(bbs_thread_id, failure_class="launch_error")
        if completed.returncode != 0:
            return self._failure(
                bbs_thread_id,
                failure_class=self._failure_class(completed.stdout, completed.stderr),
                return_code=completed.returncode,
            )
        try:
            body = output_path.read_text(encoding="utf-8", errors="replace").strip()
            output_path.chmod(0o600)
        except OSError:
            body = ""
        resolved_thread_id = bbs_thread_id or _thread_id_from_events(completed.stdout)
        if not body:
            return self._failure(bbs_thread_id, failure_class="missing_response")
        if not resolved_thread_id:
            return self._failure(bbs_thread_id, failure_class="missing_thread_id")
        return {
            "success": True,
            "body": body,
            "bbs_thread_id": resolved_thread_id,
        }

    def _command(
        self, *, turn: dict[str, Any], bbs_thread_id: str, output_path: Path
    ) -> list[str]:
        command = [
            self.settings.codex_bin,
            "exec",
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            "-c",
            f'service_tier="{self.settings.service_tier}"',
            "-C",
            str(self.settings.workdir),
            "-o",
            str(output_path),
        ]
        if self.settings.model:
            command[4:4] = ["-m", self.settings.model]
        prompt = _sms_prompt(turn)
        if bbs_thread_id:
            command.extend(("resume", bbs_thread_id, prompt))
        else:
            command.append(prompt)
        return command

    @staticmethod
    def _failure_class(stdout: str | None, stderr: str | None) -> str:
        output = f"{stdout or ''}\n{stderr or ''}".lower()
        if any(token in output for token in ("auth", "login", "credential", "api key")):
            return "authentication"
        if re.search(
            r"\b(?:model|requested)\b.{0,80}\b(?:not found|unknown|unavailable|unsupported)\b",
            output,
        ):
            return "model_unavailable"
        if any(token in output for token in ("rate limit", "quota", "capacity")):
            return "capacity"
        if any(token in output for token in ("network", "connection", "dns")):
            return "network"
        return "command_failed"

    @staticmethod
    def _failure(
        bbs_thread_id: str,
        *,
        failure_class: str,
        return_code: int | None = None,
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "event": "sms_codex_failure",
            "failure_class": failure_class,
        }
        if return_code is not None:
            event["return_code"] = return_code
        print(json.dumps(event, sort_keys=True), flush=True)
        return {
            "success": False,
            "body": "I couldn't complete that text. Please try again.",
            "bbs_thread_id": bbs_thread_id,
        }


class SmsBbsHandler(BaseHTTPRequestHandler):
    """Minimal authenticated HTTP boundary around ``SmsTurnProcessor``."""

    processor: SmsTurnProcessor
    settings: SmsBbsSettings

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _json_response(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _authorized(self) -> bool:
        if not self.settings.bbs_token:
            return True
        expected = f"Bearer {self.settings.bbs_token}"
        actual = str(self.headers.get("Authorization") or "")
        return hmac.compare_digest(actual, expected)

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] != HEALTH_PATH:
            self._json_response(HTTPStatus.NOT_FOUND, {"ok": False})
            return
        self._json_response(
            HTTPStatus.OK,
            {
                "ok": True,
                "service": "norman-sms-bbs",
                "bind": self.settings.bind,
                "port": self.settings.port,
            },
        )

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != TURN_PATH:
            self._json_response(HTTPStatus.NOT_FOUND, {"accepted": False})
            return
        if not self._authorized():
            self._json_response(
                HTTPStatus.FORBIDDEN, {"accepted": False, "error": "forbidden"}
            )
            return
        try:
            content_length = int(self.headers.get("Content-Length") or "0")
            if content_length <= 0 or content_length > 64 * 1024:
                raise SmsTurnError("invalid SMS turn body length")
            raw = self.rfile.read(content_length)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise SmsTurnError("SMS turn payload must be an object")
            accepted = self.processor.submit(payload)
        except (
            UnicodeDecodeError,
            ValueError,
            json.JSONDecodeError,
            SmsTurnError,
        ) as exc:
            self._json_response(
                HTTPStatus.BAD_REQUEST,
                {"accepted": False, "error": str(exc)},
            )
            return
        self._json_response(
            HTTPStatus.ACCEPTED,
            {
                "accepted": True,
                "conversation_id": accepted["conversation_id"],
                "turn_id": accepted["turn_id"],
            },
        )


def build_processor(
    settings: SmsBbsSettings,
    *,
    executor: Callable[[dict[str, Any], str], dict[str, Any]] | None = None,
) -> SmsTurnProcessor:
    return SmsTurnProcessor(
        state_dir=settings.state_dir / "turns",
        executor=executor or CodexSmsExecutor(settings),
        max_response_chars=settings.max_response_chars,
        callback_retry_seconds=settings.callback_retry_seconds,
    )


def create_server(
    settings: SmsBbsSettings, processor: SmsTurnProcessor
) -> ThreadingHTTPServer:
    _loopback_address(settings.bind)
    handler = type(
        "NormanSmsBbsHandler",
        (SmsBbsHandler,),
        {"processor": processor, "settings": settings},
    )
    return ThreadingHTTPServer((settings.bind, settings.port), handler)


def main() -> int:
    os.umask(0o077)
    settings = SmsBbsSettings.from_env()
    processor = build_processor(settings)
    processor.start()
    server = create_server(settings, processor)
    stop = threading.Event()

    def request_stop(_signal: int, _frame: Any) -> None:
        """Request shutdown without deadlocking the serve_forever thread."""
        stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        processor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
