"""Connector for Prometheus Alertmanager webhook payloads."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .webhook_only_connector import WebhookOnlyConnector


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


class PrometheusAlertmanagerConnector(WebhookOnlyConnector):
    id = "prometheus_alertmanager"
    name = "Prometheus Alertmanager"

    def __init__(
        self,
        webhook_url: str = "",
        receiver: str = "",
        route: str = "",
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(webhook_url=webhook_url, config=config)
        self.receiver = receiver
        self.route = route

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            normalized = await super().process_incoming(message)
            normalized.setdefault("signal_class", "passive")
            normalized.setdefault("passive_source", "prometheus_alertmanager")
            normalized.setdefault("sensor_type", "observability")
            return normalized

        status = _clean(message.get("status"))
        receiver = _clean(message.get("receiver") or self.receiver)
        alerts = (
            message.get("alerts") if isinstance(message.get("alerts"), list) else []
        )
        first = alerts[0] if alerts and isinstance(alerts[0], dict) else {}
        labels = first.get("labels") if isinstance(first.get("labels"), dict) else {}
        annotations = (
            first.get("annotations")
            if isinstance(first.get("annotations"), dict)
            else {}
        )
        alert_name = _clean(labels.get("alertname") or first.get("alertname"))
        instance = _clean(
            labels.get("instance") or labels.get("pod") or labels.get("job")
        )
        summary_txt = _clean(
            annotations.get("summary")
            or annotations.get("description")
            or message.get("message")
            or message.get("text")
        )

        text = (
            summary_txt
            or " ".join(part for part in (status, alert_name, instance) if part).strip()
        )
        if not text:
            text = "alertmanager event"

        summary = " - ".join(
            part
            for part in (
                "prometheus_alertmanager",
                status,
                receiver,
                alert_name,
                instance,
            )
            if part
        )

        return {
            "text": text,
            "text_summary": summary or "prometheus_alertmanager",
            "status": status or None,
            "receiver": receiver or None,
            "route": self.route or None,
            "alert_count": len(alerts),
            "alert_name": alert_name or None,
            "instance": instance or None,
            "group_key": message.get("groupKey"),
            "signal_class": "passive",
            "passive_source": "prometheus_alertmanager",
            "sensor_type": "observability",
        }
