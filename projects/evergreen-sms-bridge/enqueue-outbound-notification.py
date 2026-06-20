#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_ENV_PATH = ROOT / ".env"


def load_env_file(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def compact(value: Any) -> str:
    return " ".join(str(value or "").split())


def truncate(value: str, limit: int) -> str:
    text = compact(value)
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def notification_body(payload: dict[str, Any], *, limit: int = 320) -> str:
    text = compact(payload.get("text") or payload.get("body"))
    if not text:
        agent = compact(payload.get("agent")) or "Agent"
        status = compact(payload.get("status")) or "finished"
        duration = compact(payload.get("duration_label"))
        if duration:
            text = f"{agent} finished after {duration}: {status}. Open the TUI for details."
        else:
            text = f"{agent} finished: {status}. Open the TUI for details."
    return truncate(text, limit)


def expand_path(raw: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(raw))).resolve()


def latest_spool_message(spool_dir: Path) -> dict[str, Any]:
    try:
        candidates = sorted(
            (path for path in spool_dir.glob("*.json") if path.is_file()),
            key=lambda path: (path.stat().st_mtime, path.name),
            reverse=True,
        )
    except OSError:
        candidates = []
    for path in candidates:
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        message = envelope.get("message") if isinstance(envelope, dict) else None
        if isinstance(message, dict):
            sender = compact(message.get("from"))
            destination = compact(message.get("to"))
            if sender and destination:
                return message
    return {}


def resolve_sms_route() -> tuple[str, str]:
    configured_from = compact(os.getenv("SMS_NOTIFY_FROM"))
    configured_to = compact(os.getenv("SMS_NOTIFY_TO"))
    if configured_from and configured_to:
        return configured_from, configured_to

    spool_dir = expand_path(
        os.getenv("SPOOL_DIR", "~/.local/state/cloudagent/evergreen-sms/inbox")
    )
    message = latest_spool_message(spool_dir)
    inferred_from = compact(message.get("to"))
    inferred_to = compact(message.get("from"))
    from_number = configured_from or inferred_from
    to_number = configured_to or inferred_to
    if not from_number or not to_number:
        raise RuntimeError(
            "SMS_NOTIFY_FROM/SMS_NOTIFY_TO are required when no inbound SMS spool route is available"
        )
    return from_number, to_number


def build_outbound_payload(payload: dict[str, Any]) -> dict[str, Any]:
    from_number, to_number = resolve_sms_route()
    body = notification_body(payload)
    return {
        "source": "norman-long-job-notifier",
        "created_at": int(time.time()),
        "from": from_number,
        "to": to_number,
        "body": body,
        "why": "A TUI job crossed the long-job threshold and then finished.",
        "route_hint": {
            "lane": "operator notification",
            "reason": "Long-running TUI job completion.",
        },
        "profile_name": "long-job",
        "notification": {
            "type": payload.get("type") or "codex.long_job.completed",
            "agent": payload.get("agent"),
            "host": payload.get("host"),
            "status": payload.get("status"),
            "duration_seconds": payload.get("duration_seconds"),
            "finished_at": payload.get("finished_at"),
        },
    }


def enqueue_outbound(queue_url: str, payload: dict[str, Any]) -> dict[str, str]:
    import boto3

    session_kwargs: dict[str, str] = {}
    profile = compact(os.getenv("AWS_PROFILE"))
    region = compact(os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"))
    if profile:
        session_kwargs["profile_name"] = profile
    if region:
        session_kwargs["region_name"] = region
    session = boto3.Session(**session_kwargs)
    response = session.client("sqs").send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(payload, sort_keys=True),
    )
    return {
        "message_id": str(response.get("MessageId") or ""),
        "to": str(payload.get("to") or ""),
    }


def read_payload(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("notification payload must be JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("notification payload must be a JSON object")
    nested = payload.get("payload")
    if isinstance(nested, dict) and payload.get("type") != "codex.long_job.completed":
        return nested
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enqueue an operator SMS for a completed long-running TUI job."
    )
    parser.add_argument("--env", default=str(DEFAULT_ENV_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env_file(expand_path(args.env))
    raw = os.read(0, 1024 * 1024).decode("utf-8", errors="replace")
    payload = read_payload(raw)
    outbound_payload = build_outbound_payload(payload)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "ok": True,
                    "dry_run": True,
                    "to_configured": bool(outbound_payload.get("to")),
                    "from_configured": bool(outbound_payload.get("from")),
                    "body": outbound_payload.get("body"),
                },
                sort_keys=True,
            )
        )
        return 0

    queue_url = compact(os.getenv("OUTBOUND_QUEUE_URL"))
    if not queue_url:
        raise RuntimeError("OUTBOUND_QUEUE_URL is required")
    result = enqueue_outbound(queue_url, outbound_payload)
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
