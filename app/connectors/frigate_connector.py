"""Connector for Frigate NVR event payloads."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .webhook_only_connector import WebhookOnlyConnector


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


class FrigateConnector(WebhookOnlyConnector):
    id = "frigate"
    name = "Frigate"

    def __init__(
        self,
        webhook_url: str = "",
        camera: str = "",
        zone: str = "",
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(webhook_url=webhook_url, config=config)
        self.camera = camera
        self.zone = zone

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            normalized = await super().process_incoming(message)
            normalized.setdefault("signal_class", "passive")
            normalized.setdefault("passive_source", "frigate")
            normalized.setdefault("sensor_type", "vision")
            return normalized

        after = message.get("after") if isinstance(message.get("after"), dict) else {}
        event_type = _clean(message.get("type") or message.get("event"))
        camera = _clean(after.get("camera") or message.get("camera") or self.camera)
        label = _clean(after.get("label") or message.get("label"))
        sub_label = _clean(after.get("sub_label") or message.get("sub_label"))
        score = (
            after.get("score")
            if after.get("score") is not None
            else message.get("score")
        )
        event_id = _clean(after.get("id") or message.get("id"))

        entered_zones = (
            after.get("entered_zones")
            if isinstance(after.get("entered_zones"), list)
            else []
        )
        zone = _clean(
            message.get("zone")
            or (entered_zones[0] if entered_zones else "")
            or self.zone
        )

        text = _clean(
            message.get("summary")
            or message.get("description")
            or message.get("message")
            or message.get("text")
        )
        if not text:
            subject = " ".join(part for part in (label, sub_label) if part).strip()
            text = " ".join(
                part for part in (camera, event_type, subject, zone) if part
            ).strip()
        if not text:
            text = "frigate event"

        summary = " - ".join(
            part
            for part in (
                "frigate",
                camera,
                event_type,
                label,
                f"{score:.2f}" if isinstance(score, float) else str(score or ""),
            )
            if part
        )

        return {
            "text": text,
            "text_summary": summary or "frigate",
            "event_type": event_type or None,
            "camera": camera or None,
            "zone": zone or None,
            "label": label or None,
            "sub_label": sub_label or None,
            "score": score,
            "event_id": event_id or None,
            "clip_url": message.get("clip_url") or message.get("video_url"),
            "snapshot_url": message.get("snapshot_url") or message.get("image_url"),
            "signal_class": "passive",
            "passive_source": "frigate",
            "sensor_type": "vision",
        }
