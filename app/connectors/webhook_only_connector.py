"""Webhook-only connectors for services without dedicated integrations yet."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import httpx

from .base_connector import BaseConnector
from app.core.logging import setup_logger

logger = setup_logger(__name__)


class WebhookOnlyConnector(BaseConnector):
    """Minimal connector that forwards outbound messages to a webhook."""

    id = "webhook_only"
    name = "Webhook Only"

    def __init__(self, webhook_url: str = "", config: Optional[dict] = None) -> None:
        super().__init__(config)
        if not webhook_url and config:
            webhook_url = (
                config.get("webhook_url") or config.get("reply_webhook_url") or ""
            )
        self.webhook_url = webhook_url

    async def send_message(self, message: Any) -> Optional[str]:
        if not self.webhook_url:
            logger.warning("Webhook URL not configured")
            return None
        payload = message
        if isinstance(message, str):
            payload = {"text": message}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.webhook_url, json=payload)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:
                logger.error("Error sending webhook: %s", exc)
                return None

    async def listen_and_process(self) -> None:
        return None

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if isinstance(message, dict):
            text = message.get("text") or message.get("message") or ""
            if text:
                summary = f"webhook • {text}"
            else:
                summary = "webhook"
            message.setdefault("text", text)
            message.setdefault("text_summary", summary)
            return message
        text = str(message)
        summary = f"webhook • {text}" if text else "webhook"
        return {"text": text, "text_summary": summary}

    def is_connected(self) -> bool:
        return bool(self.webhook_url)


_CONNECTOR_DEFS = [
    # placeholders for connectors without bespoke classes yet
    ("circleci", "CircleCI"),
    ("jenkins", "Jenkins"),
    ("opsgenie", "Opsgenie"),
    ("servicenow", "ServiceNow"),
    ("datadog", "Datadog"),
    ("newrelic", "New Relic"),
    ("splunk", "Splunk"),
    ("cloudwatch", "AWS CloudWatch"),
    ("s3", "Amazon S3"),
    ("gdrive", "Google Drive"),
    ("dropbox", "Dropbox"),
    ("sftp", "SFTP"),
    ("airtable", "Airtable"),
    ("postgres", "PostgreSQL"),
    ("mysql", "MySQL"),
    ("bigquery", "BigQuery"),
    ("snowflake", "Snowflake"),
    ("rabbitmq", "RabbitMQ"),
]

for _id, _name in _CONNECTOR_DEFS:
    class_name = f"{_name.replace(' ', '').replace('-', '')}Connector"
    globals()[class_name] = type(
        class_name,
        (WebhookOnlyConnector,),
        {"id": _id, "name": _name},
    )

__all__ = ["WebhookOnlyConnector"] + [
    f"{name.replace(' ', '').replace('-', '')}Connector" for _, name in _CONNECTOR_DEFS
]
