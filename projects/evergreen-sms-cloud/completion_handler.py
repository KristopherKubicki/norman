"""SQS Lambda that turns a durable BBS completion into one outbound job."""

from __future__ import annotations

import json
import os
from typing import Any

import boto3

from conversation import ConversationStore


def _required_completion(payload: dict[str, Any]) -> None:
    for key in ("conversation_id", "turn_id", "sequence", "status", "success", "body"):
        if key not in payload or payload[key] in (None, ""):
            raise ValueError(f"completion is missing {key}")


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    table = boto3.resource("dynamodb").Table(os.environ["SMS_CONVERSATIONS_TABLE"])
    store = ConversationStore(table)
    sqs = boto3.client("sqs")
    failures: list[dict[str, str]] = []

    for record in event.get("Records") or []:
        message_id = str(record.get("messageId") or "")
        try:
            payload = json.loads(str(record.get("body") or "{}"))
            if not isinstance(payload, dict):
                raise ValueError("completion body must be an object")
            _required_completion(payload)
            outcome = store.record_completion(payload)
            if outcome["should_enqueue"]:
                sqs.send_message(
                    QueueUrl=os.environ["OUTBOUND_QUEUE_URL"],
                    MessageBody=json.dumps(
                        outcome["outbound_event"], separators=(",", ":")
                    ),
                )
                store.mark_outbound_enqueued(
                    str(payload["conversation_id"]), str(payload["turn_id"])
                )
        except Exception:
            if message_id:
                failures.append({"itemIdentifier": message_id})
            else:
                raise
    return {"batchItemFailures": failures}
