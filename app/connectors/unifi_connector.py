"""Connector for UniFi Network and Protect webhook events."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .webhook_only_connector import WebhookOnlyConnector


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


class UnifiConnector(WebhookOnlyConnector):
    id = "unifi"
    name = "UniFi"

    def __init__(
        self,
        webhook_url: str = "",
        controller: str = "",
        site: str = "",
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(webhook_url=webhook_url, config=config)
        self.controller = controller
        self.site = site

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            normalized = await super().process_incoming(message)
            normalized.setdefault("signal_class", "passive")
            normalized.setdefault("passive_source", "unifi")
            normalized.setdefault("sensor_type", "network")
            return normalized

        device_obj = message.get("device")
        device = ""
        if isinstance(device_obj, dict):
            device = _clean(
                device_obj.get("name")
                or device_obj.get("hostname")
                or device_obj.get("mac")
            )
        else:
            device = _clean(
                message.get("device_name")
                or message.get("device")
                or message.get("hostname")
            )

        event_type = _clean(
            message.get("event") or message.get("type") or message.get("alarm")
        )
        severity = _clean(message.get("severity") or message.get("level"))
        site = _clean(message.get("site") or self.site)
        controller = _clean(message.get("controller") or self.controller)

        text = _clean(
            message.get("message")
            or message.get("summary")
            or message.get("description")
            or message.get("text")
        )
        if not text:
            text = " ".join(
                part for part in (device, event_type, severity) if part
            ).strip()
        if not text:
            text = "unifi event"

        summary = " - ".join(
            part for part in ("unifi", site, device, event_type, severity) if part
        )

        return {
            "text": text,
            "text_summary": summary or "unifi",
            "event_type": event_type or None,
            "severity": severity or None,
            "device": device or None,
            "site": site or None,
            "controller": controller or None,
            "event_time": message.get("timestamp") or message.get("time"),
            "signal_class": "passive",
            "passive_source": "unifi",
            "sensor_type": "network",
        }
