"""Correlated local SMS bridge.

This process consumes delayed inbound jobs, resolves the merged turn from
DynamoDB, submits it to the BBS, and hosts a loopback-only completion callback.
All local acknowledgement boundaries are durable:

* inbound SQS is deleted only after BBS acceptance is written locally;
* BBS completion receives 2xx only after the completion outbox is written;
* the completion outbox is marked sent only after completion SQS accepts it.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import socket
import tempfile
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urlparse


ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CALLBACK_PATH = "/callbacks/sms"


class SmsBridgeError(RuntimeError):
    """Raised when an inbound job cannot be durably accepted."""


def log_event(event: dict[str, Any]) -> None:
    print(json.dumps(event, sort_keys=True), flush=True)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "")
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def expand_path(raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()


def credential_text(path_value: str) -> str:
    path = Path(str(path_value or "").strip()).expanduser()
    if not str(path):
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def callback_token_from_env() -> str:
    direct = os.environ.get("SMS_CALLBACK_TOKEN", "").strip()
    if direct:
        return direct
    token = credential_text(os.environ.get("SMS_CALLBACK_TOKEN_FILE", ""))
    if token:
        return token
    credentials_directory = os.environ.get("CREDENTIALS_DIRECTORY", "").strip()
    if credentials_directory:
        return credential_text(str(Path(credentials_directory) / "sms-callback-token"))
    return ""


def safe_id(value: Any, label: str) -> str:
    clean = str(value or "").strip()
    if not ID_RE.fullmatch(clean):
        raise SmsBridgeError(f"invalid {label}")
    return clean


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise SmsBridgeError(f"could not read durable state {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SmsBridgeError(f"durable state {path} is not an object")
    return value


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write private durable state with a file and directory fsync."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    serialized = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
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
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def json_compatible(value: Any) -> Any:
    """Convert DynamoDB resource values into values accepted by JSON."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {str(key): json_compatible(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_compatible(item) for item in value]
    if isinstance(value, tuple):
        return [json_compatible(item) for item in value]
    return value


def is_local_callback_url(value: str, *, allowed_hosts: set[str] | None = None) -> bool:
    """Accept only a local/private callback target, never a public endpoint."""
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in (allowed_hosts or set()):
        return True
    if hostname == "localhost":
        return True
    try:
        import ipaddress

        addresses = {
            ipaddress.ip_address(info[4][0])
            for info in socket.getaddrinfo(
                hostname, parsed.port or 80, type=socket.SOCK_STREAM
            )
        }
    except (OSError, ValueError):
        return False
    return bool(addresses) and all(
        address.is_loopback or address.is_private or address.is_link_local
        for address in addresses
    )


@dataclass(frozen=True)
class BridgeSettings:
    inbound_queue_url: str
    completion_queue_url: str
    conversations_table: str
    bbs_url: str
    bbs_token: str
    callback_bind: str
    callback_port: int
    callback_url: str
    callback_token: str
    state_dir: Path
    request_timeout_seconds: int
    poll_wait_seconds: int
    visibility_timeout_seconds: int
    max_messages: int
    outbox_retry_seconds: int
    run_once: bool

    @classmethod
    def from_env(cls) -> "BridgeSettings":
        inbound_queue_url = os.environ.get("INBOUND_QUEUE_URL", "").strip()
        completion_queue_url = os.environ.get("COMPLETION_QUEUE_URL", "").strip()
        conversations_table = os.environ.get("SMS_CONVERSATIONS_TABLE", "").strip()
        bbs_url = os.environ.get("BBS_URL", "http://127.0.0.1:8798").strip().rstrip("/")
        callback_bind = os.environ.get("SMS_CALLBACK_BIND", "127.0.0.1").strip()
        callback_port = env_int("SMS_CALLBACK_PORT", 8797)
        callback_url = os.environ.get("SMS_CALLBACK_URL", "").strip()
        if not callback_url:
            callback_url = f"http://{callback_bind}:{callback_port}{CALLBACK_PATH}"
        settings = cls(
            inbound_queue_url=inbound_queue_url,
            completion_queue_url=completion_queue_url,
            conversations_table=conversations_table,
            bbs_url=bbs_url,
            bbs_token=os.environ.get("BBS_TOKEN", "").strip(),
            callback_bind=callback_bind,
            callback_port=callback_port,
            callback_url=callback_url,
            callback_token=callback_token_from_env(),
            state_dir=expand_path(
                os.environ.get(
                    "SMS_BRIDGE_STATE_DIR",
                    "~/.local/state/cloudagent/evergreen-sms",
                )
            ),
            request_timeout_seconds=max(1, env_int("BBS_REQUEST_TIMEOUT_SEC", 20)),
            poll_wait_seconds=max(0, min(20, env_int("POLL_WAIT_TIME_SEC", 20))),
            visibility_timeout_seconds=max(30, env_int("VISIBILITY_TIMEOUT_SEC", 180)),
            max_messages=max(1, min(10, env_int("MAX_NUMBER_OF_MESSAGES", 5))),
            outbox_retry_seconds=max(1, env_int("OUTBOX_RETRY_SECONDS", 5)),
            run_once=env_bool("RUN_ONCE", False),
        )
        for name, value in (
            ("INBOUND_QUEUE_URL", settings.inbound_queue_url),
            ("COMPLETION_QUEUE_URL", settings.completion_queue_url),
            ("SMS_CONVERSATIONS_TABLE", settings.conversations_table),
            ("SMS_CALLBACK_TOKEN", settings.callback_token),
        ):
            if not value:
                raise SmsBridgeError(f"{name} is required in SMS delivery mode")
        if not is_local_callback_url(settings.callback_url):
            raise SmsBridgeError(
                "SMS_CALLBACK_URL must resolve to a loopback or private address"
            )
        return settings


def session_from_env() -> Any:
    try:
        import boto3
    except ModuleNotFoundError as exc:
        raise SmsBridgeError("boto3 is not installed; run ./install.sh first") from exc

    profile = os.environ.get("AWS_PROFILE", "").strip()
    region = os.environ.get("AWS_REGION", "us-east-2").strip() or "us-east-2"
    if profile:
        return boto3.Session(profile_name=profile, region_name=region)
    return boto3.Session(region_name=region)


def bbs_turn_payload(
    *,
    turn: dict[str, Any],
    callback_url: str,
) -> dict[str, Any]:
    conversation_id = safe_id(turn.get("conversation_id"), "conversation_id")
    turn_id = safe_id(turn.get("turn_id"), "turn_id")
    sequence = int(turn.get("sequence") or 0)
    body = str(turn.get("body") or "").strip()
    source = turn.get("source") if isinstance(turn.get("source"), dict) else {}
    if sequence <= 0 or not body:
        raise SmsBridgeError("inbound turn is missing sequence or body")
    return {
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "sequence": sequence,
        "message": body,
        "callback_url": callback_url,
        "source": {
            "from": str(source.get("from") or ""),
            "to": str(source.get("to") or ""),
            "message_sid": str(source.get("message_sid") or ""),
        },
    }


def post_bbs_turn(
    *,
    bbs_url: str,
    bbs_token: str,
    timeout_seconds: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "EvergreenSmsBridge/2.0",
    }
    if bbs_token:
        headers["Authorization"] = f"Bearer {bbs_token}"
    req = request.Request(
        f"{bbs_url}/api/sms/turns",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8", errors="replace")
        if not 200 <= int(response.status) < 300:
            raise SmsBridgeError(f"BBS returned {response.status}")
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise SmsBridgeError("BBS returned invalid JSON") from exc
    if not isinstance(parsed, dict) or parsed.get("accepted") is not True:
        raise SmsBridgeError(str(parsed.get("error") or "BBS did not accept SMS turn"))
    if (
        str(parsed.get("conversation_id") or "") != payload["conversation_id"]
        or str(parsed.get("turn_id") or "") != payload["turn_id"]
    ):
        raise SmsBridgeError("BBS acknowledgement correlation did not match")
    return parsed


class SmsBridge:
    def __init__(
        self,
        settings: BridgeSettings,
        *,
        sqs_client: Any,
        turns_table: Any,
    ) -> None:
        self.settings = settings
        self.sqs_client = sqs_client
        self.turns_table = turns_table
        self.lock = threading.RLock()
        self.turns_dir = settings.state_dir / "turns"
        self.completions_dir = settings.state_dir / "completions"
        self.turns_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.completions_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _turn_path(self, turn_id: str) -> Path:
        return self.turns_dir / f"{safe_id(turn_id, 'turn_id')}.json"

    def _completion_path(self, turn_id: str) -> Path:
        return self.completions_dir / f"{safe_id(turn_id, 'turn_id')}.json"

    def resolve_turn(self, event: dict[str, Any]) -> dict[str, Any]:
        conversation_id = safe_id(event.get("conversation_id"), "conversation_id")
        turn_id = safe_id(event.get("turn_id"), "turn_id")
        record = self.turns_table.get_item(
            Key={"pk": f"CONV#{conversation_id}", "sk": f"TURN#{turn_id}"},
            ConsistentRead=True,
        ).get("Item")
        if not isinstance(record, dict):
            raise SmsBridgeError("cloud turn is unavailable")
        if str(record.get("conversation_id") or "") != conversation_id:
            raise SmsBridgeError("cloud turn conversation mismatch")
        if str(record.get("turn_id") or "") != turn_id:
            raise SmsBridgeError("cloud turn id mismatch")
        status = str(record.get("status") or "")
        if status in {"completed", "failed"}:
            raise SmsBridgeError(f"cloud turn is already terminal ({status})")
        if status == "buffering":
            try:
                self.turns_table.update_item(
                    Key={"pk": f"CONV#{conversation_id}", "sk": f"TURN#{turn_id}"},
                    UpdateExpression=(
                        "SET #status = :claimed, claimed_at = :claimed_at, "
                        "updated_at = :claimed_at"
                    ),
                    ConditionExpression="#status = :buffering",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":claimed": "claimed",
                        ":buffering": "buffering",
                        ":claimed_at": int(time.time()),
                    },
                )
                record["status"] = "claimed"
            except Exception:
                # A concurrent bridge retry may have made the identical claim.
                current = self.turns_table.get_item(
                    Key={"pk": f"CONV#{conversation_id}", "sk": f"TURN#{turn_id}"},
                    ConsistentRead=True,
                ).get("Item")
                if not isinstance(current, dict) or str(
                    current.get("status") or ""
                ) not in {
                    "claimed",
                    "buffering",
                }:
                    raise
                record = current
        return json_compatible(record)

    def accept_inbound(self, event: dict[str, Any]) -> dict[str, Any]:
        """Durably submit one cloud turn to the BBS."""
        conversation_id = safe_id(event.get("conversation_id"), "conversation_id")
        turn_id = safe_id(event.get("turn_id"), "turn_id")
        with self.lock:
            path = self._turn_path(turn_id)
            existing = read_json(path)
            if existing and existing.get("bbs_status") == "accepted":
                if existing.get("conversation_id") != conversation_id:
                    raise SmsBridgeError("persisted turn conversation mismatch")
                return existing

            turn = self.resolve_turn(event)
            bbs_payload = bbs_turn_payload(
                turn=turn,
                callback_url=self.settings.callback_url,
            )
            state = {
                "conversation_id": conversation_id,
                "turn_id": turn_id,
                "sequence": int(turn.get("sequence") or 0),
                "turn": turn,
                "bbs_status": "pending",
                "received_at": int(time.time()),
            }
            atomic_write_json(path, state)

        accepted = post_bbs_turn(
            bbs_url=self.settings.bbs_url,
            bbs_token=self.settings.bbs_token,
            timeout_seconds=self.settings.request_timeout_seconds,
            payload=bbs_payload,
        )
        with self.lock:
            durable = read_json(path) or state
            durable.update(
                {
                    "bbs_status": "accepted",
                    "bbs_accepted_at": int(time.time()),
                    "bbs_receipt": accepted,
                }
            )
            atomic_write_json(path, durable)
            return durable

    def consume_inbound_sqs_message(
        self, sqs_message: dict[str, Any]
    ) -> dict[str, Any]:
        """Accept an inbound SQS record before acknowledging it to the queue."""
        receipt_handle = str(sqs_message.get("ReceiptHandle") or "")
        if not receipt_handle:
            raise SmsBridgeError("inbound SQS message is missing a receipt handle")
        try:
            event = json.loads(str(sqs_message.get("Body") or "{}"))
        except json.JSONDecodeError as exc:
            raise SmsBridgeError("inbound queue body must be valid JSON") from exc
        if not isinstance(event, dict):
            raise SmsBridgeError("inbound queue body must be an object")
        accepted = self.accept_inbound(event)
        if accepted.get("bbs_status") != "accepted":
            raise SmsBridgeError("BBS turn was not durably accepted")
        self.sqs_client.delete_message(
            QueueUrl=self.settings.inbound_queue_url,
            ReceiptHandle=receipt_handle,
        )
        return accepted

    def persist_completion(self, callback: dict[str, Any]) -> dict[str, Any]:
        conversation_id = safe_id(callback.get("conversation_id"), "conversation_id")
        turn_id = safe_id(callback.get("turn_id"), "turn_id")
        status = str(callback.get("status") or "")
        if status not in {"completed", "failed"}:
            raise SmsBridgeError("SMS callback must be terminal")
        success = callback.get("success")
        if not isinstance(success, bool):
            raise SmsBridgeError("SMS callback success must be boolean")
        if status != ("completed" if success else "failed"):
            raise SmsBridgeError("SMS callback status does not match success")
        body = str(callback.get("body") or "").strip()
        if not body:
            raise SmsBridgeError("SMS callback body is required")
        with self.lock:
            inbound = read_json(self._turn_path(turn_id))
            if not inbound or inbound.get("bbs_status") != "accepted":
                raise SmsBridgeError(
                    "SMS callback references an unaccepted bridge turn"
                )
            if inbound.get("conversation_id") != conversation_id:
                raise SmsBridgeError("SMS callback conversation mismatch")
            expected_sequence = int(inbound.get("sequence") or 0)
            if int(callback.get("sequence") or 0) != expected_sequence:
                raise SmsBridgeError("SMS callback sequence mismatch")

            completion = {
                "schema_version": 1,
                "source": "evergreen-sms-bridge",
                "conversation_id": conversation_id,
                "turn_id": turn_id,
                "sequence": expected_sequence,
                "status": status,
                "success": success,
                "body": body,
                "bbs_thread_id": str(callback.get("bbs_thread_id") or ""),
                "started_at": int(callback.get("started_at") or 0),
                "finished_at": int(callback.get("finished_at") or int(time.time())),
            }
            completion_path = self._completion_path(turn_id)
            existing = read_json(completion_path)
            if existing:
                stored = existing.get("completion") or {}
                if not self._completion_matches(stored, completion):
                    raise SmsBridgeError(
                        "stored SMS completion does not match callback"
                    )
                return existing

            durable = {
                "completion": completion,
                "outbox_status": "pending",
                "created_at": int(time.time()),
                "attempts": 0,
                "last_error": "",
            }
            atomic_write_json(completion_path, durable)
            return durable

    @staticmethod
    def _completion_matches(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
        try:
            existing_sequence = int(existing.get("sequence") or 0)
            incoming_sequence = int(incoming.get("sequence") or 0)
        except (TypeError, ValueError):
            return False
        return (
            str(existing.get("conversation_id") or "")
            == str(incoming.get("conversation_id") or "")
            and str(existing.get("turn_id") or "") == str(incoming.get("turn_id") or "")
            and existing_sequence == incoming_sequence
            and str(existing.get("status") or "") == str(incoming.get("status") or "")
            and existing.get("success") is incoming.get("success")
            and str(existing.get("body") or "") == str(incoming.get("body") or "")
        )

    def flush_completion_outbox(self) -> int:
        """Send every pending durable completion once and return sent count."""
        sent = 0
        for path in sorted(self.completions_dir.glob("*.json")):
            with self.lock:
                record = read_json(path)
                if not record or record.get("outbox_status") == "sent":
                    continue
                completion = record.get("completion")
                if not isinstance(completion, dict):
                    log_event(
                        {
                            "event": "completion_outbox_error",
                            "path": str(path),
                            "error": "missing_completion",
                        }
                    )
                    continue
            try:
                response = self.sqs_client.send_message(
                    QueueUrl=self.settings.completion_queue_url,
                    MessageBody=json.dumps(completion, separators=(",", ":")),
                )
            except Exception as exc:
                with self.lock:
                    durable = read_json(path) or record
                    durable["attempts"] = int(durable.get("attempts") or 0) + 1
                    durable["last_error"] = f"{type(exc).__name__}: {exc}"
                    durable["last_attempt_at"] = int(time.time())
                    atomic_write_json(path, durable)
                log_event(
                    {
                        "event": "completion_outbox_error",
                        "turn_id": completion.get("turn_id"),
                        "error": type(exc).__name__,
                        "detail": str(exc),
                    }
                )
                continue

            with self.lock:
                durable = read_json(path) or record
                durable.update(
                    {
                        "outbox_status": "sent",
                        "sent_at": int(time.time()),
                        "sqs_message_id": str(response.get("MessageId") or ""),
                        "attempts": int(durable.get("attempts") or 0) + 1,
                        "last_error": "",
                    }
                )
                atomic_write_json(path, durable)
            sent += 1
        return sent


class SmsCallbackHandler(BaseHTTPRequestHandler):
    bridge: SmsBridge

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _json_response(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != CALLBACK_PATH:
            self._json_response(HTTPStatus.NOT_FOUND, {"ok": False})
            return
        authorization = str(self.headers.get("Authorization") or "")
        expected = f"Bearer {self.bridge.settings.callback_token}"
        if not hmac.compare_digest(authorization, expected):
            self._json_response(
                HTTPStatus.FORBIDDEN, {"ok": False, "error": "forbidden"}
            )
            return
        try:
            content_length = int(self.headers.get("Content-Length") or "0")
            if content_length <= 0 or content_length > 64 * 1024:
                raise SmsBridgeError("invalid callback body length")
            raw = self.rfile.read(content_length)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise SmsBridgeError("callback payload must be an object")
            record = self.bridge.persist_completion(payload)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            SmsBridgeError,
        ) as exc:
            self._json_response(
                HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)}
            )
            return
        self._json_response(
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "turn_id": record["completion"]["turn_id"],
                "outbox_status": record["outbox_status"],
            },
        )


def start_callback_server(bridge: SmsBridge) -> ThreadingHTTPServer:
    handler = type(
        "EvergreenSmsCallbackHandler", (SmsCallbackHandler,), {"bridge": bridge}
    )
    server = ThreadingHTTPServer(
        (bridge.settings.callback_bind, bridge.settings.callback_port), handler
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def start_outbox_worker(bridge: SmsBridge, stop: threading.Event) -> threading.Thread:
    def run() -> None:
        while not stop.is_set():
            bridge.flush_completion_outbox()
            stop.wait(bridge.settings.outbox_retry_seconds)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def main() -> int:
    settings = BridgeSettings.from_env()
    session = session_from_env()
    bridge = SmsBridge(
        settings,
        sqs_client=session.client("sqs"),
        turns_table=session.resource("dynamodb").Table(settings.conversations_table),
    )
    callback_server = start_callback_server(bridge)
    stop = threading.Event()
    worker = start_outbox_worker(bridge, stop)
    log_event(
        {
            "event": "bridge_start",
            "delivery_mode": "sms",
            "inbound_queue_url": settings.inbound_queue_url,
            "completion_queue_url": settings.completion_queue_url,
            "conversations_table": settings.conversations_table,
            "callback_url": settings.callback_url,
            "state_dir": str(settings.state_dir),
        }
    )
    try:
        while True:
            response = bridge.sqs_client.receive_message(
                QueueUrl=settings.inbound_queue_url,
                AttributeNames=["All"],
                MaxNumberOfMessages=settings.max_messages,
                VisibilityTimeout=settings.visibility_timeout_seconds,
                WaitTimeSeconds=settings.poll_wait_seconds,
            )
            messages = response.get("Messages") or []
            for sqs_message in messages:
                message_id = str(sqs_message.get("MessageId") or "")
                try:
                    accepted = bridge.consume_inbound_sqs_message(sqs_message)
                    log_event(
                        {
                            "event": "bridge_bbs_accepted",
                            "message_id": message_id,
                            "conversation_id": accepted["conversation_id"],
                            "turn_id": accepted["turn_id"],
                        }
                    )
                except error.HTTPError as exc:
                    log_event(
                        {
                            "event": "bridge_error",
                            "message_id": message_id,
                            "error": "bbs_http_error",
                            "status": exc.code,
                            "detail": str(exc),
                        }
                    )
                except Exception as exc:
                    log_event(
                        {
                            "event": "bridge_error",
                            "message_id": message_id,
                            "error": type(exc).__name__,
                            "detail": str(exc),
                        }
                    )
            bridge.flush_completion_outbox()
            if settings.run_once:
                return 0
    finally:
        stop.set()
        worker.join(timeout=2)
        callback_server.shutdown()
        callback_server.server_close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log_event({"event": "bridge_stop", "reason": "keyboard_interrupt"})
        raise SystemExit(130)
