"""Connector for Snowflake event webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class SnowflakeConnector(WebhookOnlyConnector):
    id = "snowflake"
    name = "Snowflake"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        task = message.get("taskName")
        query_id = message.get("queryId")
        status = message.get("status")
        text = task or query_id or "Snowflake event"
        summary_parts = ["snowflake"]
        if status:
            summary_parts.append(str(status))
        if text:
            summary_parts.append(text)
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "task": task,
            "query_id": query_id,
            "status": status,
            "warehouse": message.get("warehouseName"),
            "database": message.get("databaseName"),
            "schema": message.get("schemaName"),
            "text_summary": summary,
        }
