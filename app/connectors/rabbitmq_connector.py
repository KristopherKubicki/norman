"""Connector for RabbitMQ event webhooks."""

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


class RabbitMQConnector(WebhookOnlyConnector):
    id = "rabbitmq"
    name = "RabbitMQ"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {"raw": message}
        return {
            "text": message.get("queue") or message.get("exchange") or "RabbitMQ event",
            "queue": message.get("queue"),
            "exchange": message.get("exchange"),
            "routing_key": message.get("routing_key"),
        }
