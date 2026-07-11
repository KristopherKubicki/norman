"""Connector for Glimpser vision events.

This adapter is webhook-oriented for now. It normalizes inbound events into a
consistent payload that routing rules can match on.
"""

from __future__ import annotations

from typing import Any, Dict

from .webhook_only_connector import WebhookOnlyConnector


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


class GlimpserConnector(WebhookOnlyConnector):
    id = "glimpser"
    name = "Glimpser"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            normalized = await super().process_incoming(message)
            normalized.setdefault("signal_class", "passive")
            normalized.setdefault("passive_source", "glimpser")
            normalized.setdefault("sensor_type", "vision")
            return normalized

        event = _clean(message.get("event") or message.get("type"))
        camera = _clean(
            message.get("camera")
            or message.get("camera_name")
            or message.get("device")
            or message.get("source")
        )
        description = _clean(
            message.get("summary")
            or message.get("description")
            or message.get("message")
            or message.get("text")
        )
        confidence = message.get("confidence")

        text = description or " ".join(part for part in (camera, event) if part).strip()
        if not text:
            text = "glimpser event"

        summary_parts = ["glimpser"]
        if camera:
            summary_parts.append(camera)
        if event:
            summary_parts.append(event)
        if description and description != text:
            summary_parts.append(description)
        if confidence is not None and str(confidence).strip():
            summary_parts.append(f"{confidence}%")
        summary = " • ".join(summary_parts)

        return {
            "text": text,
            "text_summary": summary,
            "event": event or None,
            "camera": camera or None,
            "confidence": confidence,
            "image_url": message.get("image_url") or message.get("snapshot_url"),
            "clip_url": message.get("clip_url") or message.get("video_url"),
            "signal_class": "passive",
            "passive_source": "glimpser",
            "sensor_type": "vision",
        }
