"""Twilio webhook Lambda for durable inbound Evergreen SMS acceptance."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from xml.sax.saxutils import escape
from urllib.parse import parse_qs
from typing import Any

import boto3

from conversation import ConversationStore, IncomingSms
from twilio_credentials import twilio_auth_token


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def _body_params(event: dict[str, Any]) -> dict[str, str]:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(str(body)).decode("utf-8")
    parsed = parse_qs(str(body), keep_blank_values=True)
    return {key: str(values[-1] or "") for key, values in parsed.items()}


def _request_url(event: dict[str, Any]) -> str:
    configured = os.environ.get("TWILIO_WEBHOOK_URL", "").strip()
    if configured:
        return configured
    headers = {
        str(key).lower(): str(value)
        for key, value in (event.get("headers") or {}).items()
    }
    host = headers.get("x-forwarded-host") or headers.get("host")
    if not host:
        return ""
    protocol = headers.get("x-forwarded-proto") or "https"
    raw_path = str(event.get("rawPath") or event.get("path") or "/twilio/inbound")
    raw_query = str(event.get("rawQueryString") or "")
    return f"{protocol}://{host}{raw_path}" + (f"?{raw_query}" if raw_query else "")


def twilio_signature_valid(
    *, auth_token: str, signature: str, request_url: str, params: dict[str, str]
) -> bool:
    if not auth_token or not signature or not request_url:
        return False
    signed = request_url + "".join(
        f"{key}{params[key]}" for key in sorted(params.keys())
    )
    expected = base64.b64encode(
        hmac.new(
            auth_token.encode("utf-8"), signed.encode("utf-8"), hashlib.sha1
        ).digest()
    ).decode("ascii")
    return hmac.compare_digest(expected, signature)


def _twiml_response(status: int = 200, body: str = "<Response/>") -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/xml; charset=utf-8"},
        "body": body,
    }


def _acceptance_twiml(turn_id: str) -> str:
    """Return a small, correlation-safe acknowledgement for a new SMS turn."""
    clean_turn_id = str(turn_id or "").strip()
    reference = clean_turn_id[-8:] if clean_turn_id else "pending"
    message = f"Accepted · Norman is working · turn {reference}"
    return f"<Response><Message>{escape(message)}</Message></Response>"


def _json_response(status: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json; charset=utf-8"},
        "body": json.dumps(payload, separators=(",", ":")),
    }


def _request_method(event: dict[str, Any]) -> str:
    request_context = event.get("requestContext") or {}
    http_context = request_context.get("http") or {}
    return str(http_context.get("method") or event.get("httpMethod") or "").upper()


def _allowed_senders() -> frozenset[str]:
    configured = os.environ.get("SMS_ALLOWED_FROM_NUMBERS", "")
    return frozenset(
        number.strip() for number in configured.split(",") if number.strip()
    )


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    raw_path = str(event.get("rawPath") or event.get("path") or "")
    if _request_method(event) == "GET" and raw_path == "/health":
        return _json_response(
            200,
            {
                "ok": True,
                "service": "evergreen-sms-inbound",
                "sender_allowlist_configured": bool(_allowed_senders()),
            },
        )

    params = _body_params(event)
    headers = {
        str(key).lower(): str(value)
        for key, value in (event.get("headers") or {}).items()
    }
    if os.environ.get("TWILIO_VALIDATE_SIGNATURE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }:
        if not twilio_signature_valid(
            auth_token=twilio_auth_token(),
            signature=headers.get("x-twilio-signature", ""),
            request_url=_request_url(event),
            params=params,
        ):
            return _twiml_response(403, "<Response/>")

    message_sid = params.get("MessageSid", "").strip()
    from_number = params.get("From", "").strip()
    to_number = params.get("To", "").strip()
    account_sid = params.get("AccountSid", "").strip()
    if not all((message_sid, from_number, to_number, account_sid)):
        return _twiml_response(400, "<Response/>")
    if from_number not in _allowed_senders():
        # Silently accept the Twilio delivery so unauthorized senders are not
        # given an oracle and Twilio does not retry it. Nothing is persisted or
        # queued before this fail-closed authorization check.
        print(
            json.dumps(
                {
                    "event": "sms_sender_rejected",
                    "sender_suffix": from_number[-4:],
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
        return _twiml_response()

    timestamp = _env_int("SMS_RECEIVED_AT_OVERRIDE", 0) or None
    incoming = IncomingSms(
        message_sid=message_sid,
        account_sid=account_sid,
        from_number=from_number,
        to_number=to_number,
        body=params.get("Body", ""),
        received_at=timestamp or __import__("time").time_ns() // 1_000_000_000,
        profile_name=params.get("ProfileName", ""),
    )
    table = boto3.resource("dynamodb").Table(os.environ["SMS_CONVERSATIONS_TABLE"])
    store = ConversationStore(
        table,
        idle_seconds=_env_int("SMS_CONVERSATION_IDLE_SECONDS", 24 * 60 * 60),
        burst_seconds=_env_int("SMS_BURST_SECONDS", 8),
    )
    accepted = store.accept_inbound(incoming)
    if accepted["should_dispatch"]:
        dispatch = dict(accepted["dispatch"])
        boto3.client("sqs").send_message(
            QueueUrl=os.environ["INBOUND_QUEUE_URL"],
            MessageBody=__import__("json").dumps(dispatch, separators=(",", ":")),
            DelaySeconds=int(accepted["delay_seconds"]),
        )
        store.mark_inbound_dispatched(dispatch)

    if (
        os.environ.get("SMS_ACCEPTANCE_ACK_ENABLED", "1").strip().lower()
        not in {"0", "false", "no", "off"}
        and not accepted.get("duplicate")
        and accepted.get("should_dispatch")
    ):
        dispatch = accepted.get("dispatch") or {}
        return _twiml_response(body=_acceptance_twiml(dispatch.get("turn_id", "")))
    return _twiml_response()
