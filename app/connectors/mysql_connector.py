"""Connector for MySQL change events."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class MySQLConnector(WebhookOnlyConnector):
    id = "mysql"
    name = "MySQL"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        table = message.get("table")
        operation = message.get("operation")
        text = table or operation or "MySQL event"
        summary_parts = ["mysql"]
        if operation:
            summary_parts.append(str(operation))
        if table:
            summary_parts.append(str(table))
        summary = " • ".join(part for part in summary_parts if part)
        return {
            "text": text,
            "table": table,
            "operation": operation,
            "schema": message.get("schema"),
            "primary_key": message.get("primary_key"),
            "text_summary": summary,
        }
