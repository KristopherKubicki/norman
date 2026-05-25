#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict
from urllib import error, request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "")
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return int(raw)


def env_str(name: str, default: str = "") -> str:
    value = os.getenv(name, "")
    if not value:
        return default
    return value.strip()


def expand_path(raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()


def log_event(event: Dict[str, Any]) -> None:
    print(json.dumps(event, sort_keys=True), flush=True)


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tmp_path.replace(path)


def spool_message(spool_dir: Path, envelope: Dict[str, Any]) -> str:
    message = envelope.get("message") or {}
    message_sid = str(message.get("message_sid") or "unknown")
    received_at = int(envelope.get("bridge_received_at") or int(time.time()))
    filename = f"{received_at}-{message_sid}.json"
    path = spool_dir / filename
    write_json(path, envelope)
    return str(path)


def post_webhook(webhook_url: str, timeout_sec: int, envelope: Dict[str, Any]) -> int:
    payload = json.dumps(envelope, sort_keys=True).encode("utf-8")
    message_sid = str(((envelope.get("message") or {}).get("message_sid")) or "")
    req = request.Request(
        webhook_url,
        data=payload,
        method="POST",
        headers={
            "content-type": "application/json",
            "x-evergreen-message-sid": message_sid,
        },
    )
    with request.urlopen(req, timeout=timeout_sec) as response:
        return int(response.status)


def collector_action_url(base_url: str, collector_token: str) -> str:
    return collector_endpoint_url(base_url, collector_token, "/api/ask")


def collector_endpoint_url(base_url: str, collector_token: str, path: str) -> str:
    normalized = str(base_url or "").strip()
    if not normalized:
        raise RuntimeError("collector URL is unavailable")

    parts = urlsplit(normalized)
    if not parts.scheme or not parts.netloc:
        raise RuntimeError("collector URL must be absolute")

    query_items = {
        key: value for key, value in parse_qsl(parts.query, keep_blank_values=True)
    }
    token = (
        str(collector_token or "").strip()
        or str(query_items.get("token") or "").strip()
    )
    action_query = {"token": token} if token else {}
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            path,
            urlencode(action_query),
            "",
        )
    )


def collector_status_url(base_url: str, collector_token: str) -> str:
    return collector_endpoint_url(base_url, collector_token, "/api/status")


def prompt_contains_marker(prompt_probe: str, markers: list[str]) -> bool:
    normalized_probe = compact_whitespace(prompt_probe)
    for raw_marker in markers:
        marker = compact_whitespace(raw_marker)
        if marker and marker in normalized_probe:
            return True
    return False


def post_collector(
    *,
    collector_url: str,
    collector_token: str,
    timeout_sec: int,
    message_text: str,
) -> Dict[str, Any]:
    action_url = collector_action_url(collector_url, collector_token)
    body = urlencode({"message": message_text}).encode("utf-8")
    req = request.Request(
        action_url,
        data=body,
        method="POST",
        headers={
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
            "user-agent": "EvergreenSmsBridge/1.0",
        },
    )
    with request.urlopen(req, timeout=timeout_sec) as response:
        raw = response.read().decode("utf-8", errors="replace")
        parsed: Dict[str, Any] = {}
        if raw:
            try:
                maybe_parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError("collector returned invalid JSON") from exc
            if not isinstance(maybe_parsed, dict):
                raise RuntimeError("collector returned unexpected response")
            parsed = maybe_parsed
        if parsed.get("accepted") is False:
            raise RuntimeError(str(parsed.get("error") or "collector rejected message"))
        snapshot = (
            parsed.get("snapshot") if isinstance(parsed.get("snapshot"), dict) else {}
        )
        return {
            "status": int(response.status),
            "accepted": parsed.get("accepted", True),
            "pending": parsed.get("pending"),
            "snapshot_state": snapshot.get("state"),
            "snapshot_pending": snapshot.get("pending"),
            "snapshot_running_prompt": snapshot.get("running_prompt"),
            "snapshot_last_prompt": snapshot.get("last_prompt"),
        }


def fetch_collector_status(
    *,
    collector_url: str,
    collector_token: str,
    timeout_sec: int,
) -> Dict[str, Any]:
    status_url = collector_status_url(collector_url, collector_token)
    req = request.Request(
        status_url,
        method="GET",
        headers={
            "accept": "application/json",
            "user-agent": "EvergreenSmsBridge/1.0",
        },
    )
    with request.urlopen(req, timeout=timeout_sec) as response:
        raw = response.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("collector status returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("collector status returned unexpected response")
    return parsed


def await_collector_result(
    *,
    collector_url: str,
    collector_token: str,
    timeout_sec: int,
    poll_interval_sec: int,
    prompt_markers: list[str],
) -> Dict[str, Any]:
    deadline = time.time() + max(timeout_sec, 1)
    latest: Dict[str, Any] = {}
    while time.time() < deadline:
        latest = fetch_collector_status(
            collector_url=collector_url,
            collector_token=collector_token,
            timeout_sec=max(timeout_sec, 1),
        )
        prompt_probe = "\n".join(
            [
                str(latest.get("running_prompt") or ""),
                str(latest.get("last_prompt") or ""),
            ]
        )
        if prompt_contains_marker(prompt_probe, prompt_markers) and not bool(
            latest.get("pending")
        ):
            return latest
        time.sleep(max(1, poll_interval_sec))
    raise RuntimeError(
        "collector result timed out"
        + (f"; latest state={latest.get('state')!r}" if latest else "")
    )


def tmux_send(
    *,
    target: str,
    message_text: str,
    socket_path: str,
    working_dir: str,
    send_enter: bool,
    enter_count: int,
) -> Dict[str, Any]:
    tmux_cmd = ["tmux"]
    if socket_path:
        tmux_cmd.extend(["-S", socket_path])

    def _run(*args: str) -> None:
        subprocess.run(
            [*tmux_cmd, *args],
            check=True,
            capture_output=True,
            text=True,
        )

    if working_dir:
        _run("send-keys", "-t", target, "-l", f"cd {working_dir}")
        _run("send-keys", "-t", target, "C-m")

    _run("send-keys", "-t", target, "-l", message_text)
    if send_enter:
        for _ in range(max(1, enter_count)):
            _run("send-keys", "-t", target, "C-m")

    return {
        "target": target,
        "working_dir": working_dir,
        "send_enter": send_enter,
        "enter_count": max(1, enter_count),
    }


def build_envelope(
    message: Dict[str, Any], delivery_mode: str, queue_url: str
) -> Dict[str, Any]:
    return {
        "bridge_received_at": int(time.time()),
        "bridge_hostname": socket.gethostname(),
        "delivery_mode": delivery_mode,
        "source_queue_url": queue_url,
        "message": message,
    }


def session_from_env():
    try:
        import boto3
    except ModuleNotFoundError as exc:
        raise RuntimeError("boto3 is not installed; run ./install.sh first") from exc

    profile = os.getenv("AWS_PROFILE", "").strip()
    region = os.getenv("AWS_REGION", "us-east-2").strip() or "us-east-2"
    if profile:
        return boto3.Session(profile_name=profile, region_name=region)
    return boto3.Session(region_name=region)


def normalize_delivery_modes(raw: str) -> tuple[str, set[str]]:
    value = (raw or "").strip().lower() or "spool"
    alias_map = {
        "spool": {"spool"},
        "webhook": {"webhook"},
        "collector": {"collector"},
        "tmux": {"tmux"},
        "both": {"spool", "webhook"},
        "all": {"spool", "webhook", "collector", "tmux"},
    }
    if value in alias_map:
        modes = set(alias_map[value])
    else:
        tokens = [part for part in re.split(r"[\s,+]+", value) if part]
        if not tokens:
            raise ValueError("DELIVERY_MODE cannot be empty")
        modes = set()
        for token in tokens:
            if token not in {"spool", "webhook", "collector", "tmux"}:
                raise ValueError(
                    f"unsupported DELIVERY_MODE token {token!r}; expected spool, webhook, collector, tmux, both, or all"
                )
            modes.add(token)

    return (",".join(sorted(modes)), modes)


def format_tmux_message(message: Dict[str, Any]) -> str:
    sender = str(message.get("from") or "").strip()
    destination = str(message.get("to") or "").strip()
    profile_name = str(message.get("profile_name") or "").strip()
    message_sid = str(message.get("message_sid") or "").strip()
    body = str(message.get("body") or "").strip()

    meta_bits = []
    if sender:
        meta_bits.append(f"from {sender}")
    if destination:
        meta_bits.append(f"to {destination}")
    if profile_name:
        meta_bits.append(f"profile {profile_name}")
    if message_sid:
        meta_bits.append(f"sid {message_sid}")

    prefix = "[Evergreen SMS]"
    if meta_bits:
        prefix = f"[Evergreen SMS {' | '.join(meta_bits)}]"

    if body:
        return f"{prefix} {body}".strip()
    return prefix


def infer_overlay_hint(body_text: str) -> str:
    lowered = str(body_text or "").strip().lower()
    if re.match(r"^(work|family|private)\s*[:\-]\s*", lowered):
        return lowered.split(":", 1)[0].split("-", 1)[0].strip()
    return ""


def infer_route_hint(message: Dict[str, Any]) -> Dict[str, str]:
    body_text = compact_whitespace(message.get("body") or "")
    lowered = body_text.lower()
    overlay = infer_overlay_hint(body_text)

    netops_keywords = (
        "network",
        "synology",
        "router",
        "switch",
        "wifi",
        "lan",
        "wan",
        "vlan",
        "dns",
        "domain",
        "caddy",
        "proxy",
        "frontdoor",
        "firewall",
        "pfsense",
        "dhcp",
        "unbound",
        "resolver",
        "tailnet",
        "tailscale",
        "tls",
        "cert",
        "certificate",
        "nas",
        "server",
    )
    access_keywords = (
        "login",
        "signin",
        "sign in",
        "password",
        "passcode",
        "mfa",
        "2fa",
        "auth",
        "token",
        "secret",
        "credential",
        "api key",
        "sso",
        "godaddy",
        "squarespace",
        "github",
        "twilio",
        "aws",
    )

    lane = "Subprime default broker"
    reason = "Default broker path; no stronger routing hint."
    if any(keyword in lowered for keyword in netops_keywords):
        lane = "NetOps via Subprime"
        reason = "NetOps hint from network, infrastructure, or device-status terms."
    elif any(keyword in lowered for keyword in access_keywords):
        lane = "Subprime access path"
        reason = "Access or credential hint from the message content."

    if overlay:
        lane = f"{overlay.title()} overlay, {lane}"
        reason = f"{overlay.title()} overlay requested. {reason}"

    return {"lane": lane, "reason": reason}


def format_collector_message(message: Dict[str, Any]) -> str:
    max_chars = max(80, env_int("SMS_REPLY_MAX_CHARS", 320))
    max_sentences = max(1, env_int("SMS_REPLY_MAX_SENTENCES", 3))
    mode_label = env_str("SMS_REPLY_MODE_LABEL", "Operator SMS for Norman")
    route_hint = infer_route_hint(message)
    sender = str(message.get("from") or "").strip()
    destination = str(message.get("to") or "").strip()
    body = compact_whitespace(message.get("body") or "")
    details = []
    if sender:
        details.append(f"from {sender}")
    if destination:
        details.append(f"to {destination}")
    header = "Incoming SMS"
    if details:
        header = f"{header} ({', '.join(details)})"
    return (
        f"{mode_label}.\n"
        f"Preferred handling: {route_hint['lane']}.\n"
        "If another Norman lane is better suited, hand it off internally and return the best available answer.\n"
        f"Reply as Norman directly to the operator. Start with the answer or next action. Keep it under {max_chars} characters and at most {max_sentences} short sentences.\n"
        "Plain text only. Do not use markdown, bullets, code fences, or internal routing labels unless they matter.\n\n"
        f"{header}:\n{body or '[empty message]'}"
    )


def compact_whitespace(value: str) -> str:
    return " ".join(str(value or "").split())


def truncate_sentences(value: str, max_sentences: int) -> str:
    text = compact_whitespace(value)
    if max_sentences <= 0 or not text:
        return text
    sentences = [
        part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()
    ]
    if len(sentences) <= max_sentences:
        return text
    return " ".join(sentences[:max_sentences])


def truncate_text(value: str, max_chars: int) -> str:
    text = compact_whitespace(value)
    if len(text) <= max_chars:
        return text
    return text[: max(1, max_chars - 1)].rstrip() + "…"


def parse_structured_reply(response_text: str) -> Dict[str, str]:
    sms_lines: list[str] = []
    why_lines: list[str] = []
    active = ""
    for raw_line in str(response_text or "").splitlines():
        line = raw_line.strip()
        upper = line.upper()
        if upper.startswith("SMS:"):
            active = "sms"
            sms_lines = [line[4:].strip()]
            continue
        if upper.startswith("WHY:"):
            active = "why"
            why_lines = [line[4:].strip()]
            continue
        if active == "sms":
            sms_lines.append(line)
            continue
        if active == "why":
            why_lines.append(line)

    sms_text = compact_whitespace(" ".join(part for part in sms_lines if part))
    why_text = compact_whitespace(" ".join(part for part in why_lines if part))
    if sms_text and not why_text:
        inline_parts = re.split(r"\bWHY:\s*", sms_text, maxsplit=1, flags=re.IGNORECASE)
        if len(inline_parts) == 2:
            sms_text = compact_whitespace(inline_parts[0])
            why_text = compact_whitespace(inline_parts[1])
    if not sms_text:
        sms_text = compact_whitespace(response_text)
    return {"sms_text": sms_text, "why": why_text}


def build_outbound_reply(
    *,
    message: Dict[str, Any],
    collector_snapshot: Dict[str, Any],
    max_chars: int,
    max_sentences: int,
) -> Dict[str, Any]:
    last_response = str(collector_snapshot.get("last_response") or "").strip()
    last_error = str(collector_snapshot.get("last_error") or "").strip()
    parsed = parse_structured_reply(last_response)
    route_hint = infer_route_hint(message)
    sms_text = truncate_text(
        truncate_sentences(parsed.get("sms_text") or "", max_sentences),
        max_chars,
    )
    if not sms_text:
        sms_text = "Norman got your text. A follow-up is still pending."
    why_text = parsed.get("why") or last_error or route_hint["reason"]
    return {
        "source": "evergreen-sms-bridge",
        "created_at": int(time.time()),
        "in_reply_to_message_sid": str(message.get("message_sid") or ""),
        "account_sid": str(message.get("account_sid") or ""),
        "from": str(message.get("to") or ""),
        "to": str(message.get("from") or ""),
        "body": sms_text,
        "why": truncate_text(why_text, 240) if why_text else "",
        "route_hint": route_hint,
        "profile_name": str(message.get("profile_name") or ""),
        "collector_snapshot": {
            "state": collector_snapshot.get("state"),
            "last_prompt": collector_snapshot.get("last_prompt"),
            "last_response": collector_snapshot.get("last_response"),
            "last_error": collector_snapshot.get("last_error"),
            "last_finished_at": collector_snapshot.get("last_finished_at"),
        },
    }


def enqueue_outbound_reply(
    *,
    sqs_client: Any,
    queue_url: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    response = sqs_client.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(payload, sort_keys=True),
    )
    return {
        "queue_url": queue_url,
        "message_id": str(response.get("MessageId") or ""),
        "to": payload.get("to"),
        "body": payload.get("body"),
        "why": payload.get("why"),
    }


def main() -> int:
    queue_url = os.getenv("INBOUND_QUEUE_URL", "").strip()
    if not queue_url:
        raise RuntimeError("INBOUND_QUEUE_URL is required")

    delivery_mode, delivery_modes = normalize_delivery_modes(
        os.getenv("DELIVERY_MODE", "spool")
    )
    keep_spool_copy = env_bool("KEEP_SPOOL_COPY", True)
    spool_dir = expand_path(
        os.getenv("SPOOL_DIR", "~/.local/state/cloudagent/evergreen-sms/inbox")
    )
    webhook_url = os.getenv("WEBHOOK_URL", "").strip()
    webhook_timeout_sec = env_int("WEBHOOK_TIMEOUT_SEC", 10)
    collector_url = os.getenv("COLLECTOR_URL", "").strip()
    collector_token = os.getenv("COLLECTOR_TOKEN", "").strip()
    collector_timeout_sec = env_int("COLLECTOR_TIMEOUT_SEC", 10)
    collector_result_timeout_sec = env_int("COLLECTOR_RESULT_TIMEOUT_SEC", 90)
    collector_result_poll_sec = env_int("COLLECTOR_RESULT_POLL_SEC", 2)
    outbound_queue_url = os.getenv("OUTBOUND_QUEUE_URL", "").strip()
    tmux_target = os.getenv("TMUX_TARGET", "").strip()
    tmux_socket_path = os.getenv("TMUX_SOCKET_PATH", "").strip()
    tmux_working_dir = os.getenv("TMUX_WORKING_DIR", "").strip()
    tmux_send_enter = env_bool("TMUX_SEND_ENTER", True)
    tmux_enter_count = env_int("TMUX_ENTER_COUNT", 1)
    poll_wait_time_sec = env_int("POLL_WAIT_TIME_SEC", 20)
    visibility_timeout_sec = env_int("VISIBILITY_TIMEOUT_SEC", 120)
    max_number_of_messages = env_int("MAX_NUMBER_OF_MESSAGES", 5)
    run_once = env_bool("RUN_ONCE", False)
    sms_reply_max_chars = max(80, env_int("SMS_REPLY_MAX_CHARS", 320))
    sms_reply_max_sentences = max(1, env_int("SMS_REPLY_MAX_SENTENCES", 3))

    if "webhook" in delivery_modes and not webhook_url:
        raise RuntimeError(
            "WEBHOOK_URL is required when DELIVERY_MODE includes webhook"
        )
    if "collector" in delivery_modes and not collector_url:
        raise RuntimeError(
            "COLLECTOR_URL is required when DELIVERY_MODE includes collector"
        )
    if "tmux" in delivery_modes and not tmux_target:
        raise RuntimeError("TMUX_TARGET is required when DELIVERY_MODE includes tmux")
    if outbound_queue_url and "collector" not in delivery_modes:
        raise RuntimeError(
            "OUTBOUND_QUEUE_URL currently requires DELIVERY_MODE to include collector"
        )

    session = session_from_env()
    sqs_client = session.client("sqs")

    log_event(
        {
            "event": "bridge_start",
            "delivery_mode": delivery_mode,
            "delivery_modes": sorted(delivery_modes),
            "keep_spool_copy": keep_spool_copy,
            "queue_url": queue_url,
            "spool_dir": str(spool_dir),
            "webhook_url": webhook_url,
            "collector_url": collector_url,
            "outbound_queue_url": outbound_queue_url,
            "tmux_target": tmux_target,
        }
    )

    while True:
        response = sqs_client.receive_message(
            QueueUrl=queue_url,
            AttributeNames=["All"],
            MaxNumberOfMessages=max_number_of_messages,
            MessageAttributeNames=["All"],
            VisibilityTimeout=visibility_timeout_sec,
            WaitTimeSeconds=poll_wait_time_sec,
        )
        messages = response.get("Messages") or []
        if not messages:
            log_event({"event": "poll_idle"})
            if run_once:
                return 0
            continue

        for sqs_message in messages:
            receipt_handle = sqs_message["ReceiptHandle"]
            raw_body = sqs_message.get("Body") or "{}"
            try:
                message = json.loads(raw_body)
            except json.JSONDecodeError as exc:
                log_event(
                    {
                        "event": "bridge_error",
                        "error": "invalid_json",
                        "detail": str(exc),
                    }
                )
                continue

            envelope = build_envelope(message, delivery_mode, queue_url)
            message_sid = str(message.get("message_sid") or "unknown")
            spool_path = ""
            webhook_status = None
            collector_status = None
            outbound_status = None
            tmux_status = None

            try:
                if "spool" in delivery_modes or keep_spool_copy:
                    spool_path = spool_message(spool_dir, envelope)

                if "webhook" in delivery_modes:
                    webhook_status = post_webhook(
                        webhook_url, webhook_timeout_sec, envelope
                    )
                    if webhook_status < 200 or webhook_status >= 300:
                        raise RuntimeError(f"webhook returned status {webhook_status}")

                if "collector" in delivery_modes:
                    collector_message = format_collector_message(message)
                    collector_status = post_collector(
                        collector_url=collector_url,
                        collector_token=collector_token,
                        timeout_sec=collector_timeout_sec,
                        message_text=collector_message,
                    )
                    if (
                        collector_status["status"] < 200
                        or collector_status["status"] >= 300
                    ):
                        raise RuntimeError(
                            f"collector returned status {collector_status['status']}"
                        )

                if "tmux" in delivery_modes:
                    tmux_status = tmux_send(
                        target=tmux_target,
                        message_text=format_tmux_message(message),
                        socket_path=tmux_socket_path,
                        working_dir=tmux_working_dir,
                        send_enter=tmux_send_enter,
                        enter_count=tmux_enter_count,
                    )

                if outbound_queue_url:
                    try:
                        collector_snapshot = await_collector_result(
                            collector_url=collector_url,
                            collector_token=collector_token,
                            timeout_sec=collector_result_timeout_sec,
                            poll_interval_sec=collector_result_poll_sec,
                            prompt_markers=[
                                collector_message,
                                str(message.get("body") or ""),
                                str(message.get("from") or ""),
                            ],
                        )
                        outbound_payload = build_outbound_reply(
                            message=message,
                            collector_snapshot=collector_snapshot,
                            max_chars=sms_reply_max_chars,
                            max_sentences=sms_reply_max_sentences,
                        )
                        outbound_status = enqueue_outbound_reply(
                            sqs_client=sqs_client,
                            queue_url=outbound_queue_url,
                            payload=outbound_payload,
                        )
                    except Exception as exc:
                        log_event(
                            {
                                "event": "bridge_outbound_error",
                                "message_sid": message_sid,
                                "error": type(exc).__name__,
                                "detail": str(exc),
                            }
                        )

                sqs_client.delete_message(
                    QueueUrl=queue_url, ReceiptHandle=receipt_handle
                )
                log_event(
                    {
                        "event": "bridge_delivered",
                        "message_sid": message_sid,
                        "spool_path": spool_path,
                        "webhook_status": webhook_status,
                        "collector_status": collector_status,
                        "outbound_status": outbound_status,
                        "tmux_status": tmux_status,
                    }
                )
            except error.HTTPError as exc:
                log_event(
                    {
                        "event": "bridge_error",
                        "message_sid": message_sid,
                        "error": "webhook_http_error",
                        "status": exc.code,
                        "detail": str(exc),
                    }
                )
            except Exception as exc:
                log_event(
                    {
                        "event": "bridge_error",
                        "message_sid": message_sid,
                        "error": type(exc).__name__,
                        "detail": str(exc),
                    }
                )

        if run_once:
            return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log_event({"event": "bridge_stop", "reason": "keyboard_interrupt"})
        raise SystemExit(130)
    except Exception as exc:
        log_event(
            {"event": "bridge_fatal", "error": type(exc).__name__, "detail": str(exc)}
        )
        raise
