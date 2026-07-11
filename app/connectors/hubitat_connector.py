"""Connector for Hubitat events.

Hubitat Maker API and webhook automations typically POST compact JSON event
documents. This connector normalizes those payloads for Norman routing.
"""

from __future__ import annotations

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


class HubitatConnector(WebhookOnlyConnector):
    id = "hubitat"
    name = "Hubitat"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            normalized = await super().process_incoming(message)
            normalized.setdefault("signal_class", "passive")
            normalized.setdefault("passive_source", "hubitat")
            normalized.setdefault("sensor_type", "home_automation")
            return normalized

        device = _clean(
            message.get("displayName")
            or message.get("deviceName")
            or message.get("device")
        )
        attribute = _clean(message.get("name") or message.get("attribute"))
        raw_value = message.get("value")
        value = _clean(raw_value)
        description = _clean(
            message.get("descriptionText") or message.get("description")
        )

        text = (
            description
            or " ".join(part for part in (device, attribute, value) if part).strip()
            or "hubitat event"
        )
        summary_parts = ["hubitat"]
        if device:
            summary_parts.append(device)
        if attribute:
            summary_parts.append(attribute)
        if value and value != description:
            summary_parts.append(value)
        summary = " • ".join(summary_parts)

        return {
            "text": text,
            "text_summary": summary,
            "device": device or None,
            "device_id": message.get("deviceId") or message.get("device_id"),
            "attribute": attribute or None,
            "value": raw_value,
            "unit": message.get("unit") or message.get("units"),
            "source": message.get("source"),
            "location": message.get("locationId") or message.get("location"),
            "signal_class": "passive",
            "passive_source": "hubitat",
            "sensor_type": "home_automation",
        }
