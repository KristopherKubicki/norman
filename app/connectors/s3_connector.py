"""Connector for Amazon S3 webhook notifications."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class S3Connector(WebhookOnlyConnector):
    id = "s3"
    name = "Amazon S3"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        records = message.get("Records") or []
        record = records[0] if records else {}
        s3 = record.get("s3") or {}
        bucket = (s3.get("bucket") or {}).get("name")
        obj = (s3.get("object") or {}).get("key")
        event_name = record.get("eventName")
        summary_parts = ["s3"]
        if event_name:
            summary_parts.append(event_name)
        if obj:
            summary_parts.append(obj)
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": obj or "S3 event",
            "bucket": bucket,
            "object_key": obj,
            "event": event_name,
            "size": (s3.get("object") or {}).get("size"),
            "region": record.get("awsRegion"),
            "text_summary": summary,
        }
