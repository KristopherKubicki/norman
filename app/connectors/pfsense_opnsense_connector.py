"""Connector for pfSense and OPNsense webhook events."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .webhook_only_connector import WebhookOnlyConnector


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


class PfSenseOPNsenseConnector(WebhookOnlyConnector):
    id = "pfsense_opnsense"
    name = "pfSense / OPNsense"

    def __init__(
        self,
        webhook_url: str = "",
        firewall: str = "",
        event_filter: str = "",
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(webhook_url=webhook_url, config=config)
        self.firewall = firewall
        self.event_filter = event_filter

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            normalized = await super().process_incoming(message)
            normalized.setdefault("signal_class", "passive")
            normalized.setdefault("passive_source", "pfsense_opnsense")
            normalized.setdefault("sensor_type", "firewall")
            return normalized

        firewall = _clean(
            message.get("firewall")
            or message.get("host")
            or message.get("node")
            or self.firewall
        )
        event_type = _clean(
            message.get("event")
            or message.get("type")
            or message.get("subsystem")
            or message.get("rule")
        )
        action = _clean(message.get("action") or message.get("state"))
        src_ip = _clean(message.get("src_ip") or message.get("source_ip"))
        dst_ip = _clean(message.get("dst_ip") or message.get("destination_ip"))
        protocol = _clean(message.get("proto") or message.get("protocol"))
        rule = _clean(message.get("rule") or message.get("rule_id"))

        text = _clean(
            message.get("message")
            or message.get("summary")
            or message.get("description")
            or message.get("text")
        )
        if not text:
            endpoint = " -> ".join(part for part in (src_ip, dst_ip) if part)
            text = " ".join(
                part
                for part in (firewall, event_type, action, protocol, endpoint)
                if part
            ).strip()
        if not text:
            text = "firewall event"

        summary = " - ".join(
            part
            for part in ("pfsense_opnsense", firewall, event_type, action, rule)
            if part
        )

        return {
            "text": text,
            "text_summary": summary or "pfsense_opnsense",
            "firewall": firewall or None,
            "event_type": event_type or None,
            "action": action or None,
            "src_ip": src_ip or None,
            "dst_ip": dst_ip or None,
            "protocol": protocol or None,
            "rule": rule or None,
            "signal_class": "passive",
            "passive_source": "pfsense_opnsense",
            "sensor_type": "firewall",
        }
