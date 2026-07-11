"""Connector for Proxmox cluster and VM event webhooks."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .webhook_only_connector import WebhookOnlyConnector


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


class ProxmoxConnector(WebhookOnlyConnector):
    id = "proxmox"
    name = "Proxmox"

    def __init__(
        self,
        webhook_url: str = "",
        cluster: str = "",
        node: str = "",
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(webhook_url=webhook_url, config=config)
        self.cluster = cluster
        self.node = node

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            normalized = await super().process_incoming(message)
            normalized.setdefault("signal_class", "passive")
            normalized.setdefault("passive_source", "proxmox")
            normalized.setdefault("sensor_type", "virtualization")
            return normalized

        event_type = _clean(message.get("event") or message.get("type"))
        node = _clean(message.get("node") or self.node)
        cluster = _clean(message.get("cluster") or self.cluster)
        vmid = message.get("vmid") or message.get("guest_id") or message.get("id")
        guest = _clean(
            message.get("guest")
            or message.get("vm_name")
            or message.get("name")
            or message.get("resource")
        )
        status = _clean(message.get("status") or message.get("state"))

        text = _clean(
            message.get("message")
            or message.get("summary")
            or message.get("description")
            or message.get("text")
        )
        if not text:
            vm_label = guest or (f"vm:{vmid}" if vmid else "")
            text = " ".join(
                part for part in (cluster, node, vm_label, event_type, status) if part
            ).strip()
        if not text:
            text = "proxmox event"

        summary = " - ".join(
            part
            for part in (
                "proxmox",
                cluster,
                node,
                guest or (str(vmid) if vmid is not None else ""),
                event_type,
                status,
            )
            if part
        )

        return {
            "text": text,
            "text_summary": summary or "proxmox",
            "event_type": event_type or None,
            "cluster": cluster or None,
            "node": node or None,
            "vmid": vmid,
            "guest": guest or None,
            "status": status or None,
            "signal_class": "passive",
            "passive_source": "proxmox",
            "sensor_type": "virtualization",
        }
