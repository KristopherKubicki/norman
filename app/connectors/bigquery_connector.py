"""Connector for BigQuery event webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class BigQueryConnector(WebhookOnlyConnector):
    id = "bigquery"
    name = "BigQuery"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        return {
            "text": message.get("jobId") or message.get("table") or "BigQuery event",
            "job_id": message.get("jobId"),
            "dataset": message.get("dataset"),
            "table": message.get("table"),
        }
