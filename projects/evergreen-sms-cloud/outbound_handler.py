"""SQS Lambda that sends exactly-correlated replies through Twilio."""

from __future__ import annotations

import base64
import json
import os
from typing import Any
from urllib import error, parse, request

import boto3

from conversation import ConversationStore
from twilio_credentials import twilio_auth_token


def _twilio_send(payload: dict[str, Any]) -> str:
    account_sid = str(
        payload.get("account_sid") or os.environ.get("TWILIO_ACCOUNT_SID") or ""
    )
    auth_token = twilio_auth_token()
    from_number = str(payload.get("from") or "")
    to_number = str(payload.get("to") or "")
    body = str(payload.get("body") or "").strip()
    if not all((account_sid, auth_token, from_number, to_number, body)):
        raise ValueError("outbound SMS is missing Twilio account, route, or body")

    encoded = parse.urlencode(
        {"From": from_number, "To": to_number, "Body": body}
    ).encode("utf-8")
    authorization = base64.b64encode(
        f"{account_sid}:{auth_token}".encode("utf-8")
    ).decode("ascii")
    req = request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
        data=encoded,
        method="POST",
        headers={
            "Authorization": f"Basic {authorization}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with request.urlopen(req, timeout=15) as response:
            decoded = response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Twilio rejected outbound SMS: {exc.code} {detail[:300]}"
        ) from exc
    parsed = json.loads(decoded or "{}")
    provider_sid = str(parsed.get("sid") or "")
    if not provider_sid:
        raise RuntimeError("Twilio response did not include a message sid")
    return provider_sid


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    table = boto3.resource("dynamodb").Table(os.environ["SMS_CONVERSATIONS_TABLE"])
    store = ConversationStore(table)
    failures: list[dict[str, str]] = []
    for record in event.get("Records") or []:
        message_id = str(record.get("messageId") or "")
        try:
            payload = json.loads(str(record.get("body") or "{}"))
            if not isinstance(payload, dict):
                raise ValueError("outbound body must be an object")
            turn_id = str(payload.get("turn_id") or "")
            if not turn_id:
                raise ValueError("outbound SMS is missing turn_id")
            lease = store.begin_outbound(turn_id)
            if lease:
                provider_sid = _twilio_send(payload)
                store.mark_outbound_sent(
                    turn_id, provider_sid, str(lease["lease_token"])
                )
        except Exception:
            if message_id:
                failures.append({"itemIdentifier": message_id})
            else:
                raise
    return {"batchItemFailures": failures}
