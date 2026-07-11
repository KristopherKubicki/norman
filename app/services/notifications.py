"""Notification helpers.

Currently used for pushing operator-relevant events (like command approvals)
into a webhook endpoint for phone-first workflows.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from app.core.config import get_settings
from app.core.logging import setup_logger

logger = setup_logger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(text: str, limit: int = 240) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "..."


async def send_webhook_notification(
    *,
    event_type: str,
    payload: Dict[str, Any],
    url: str,
    timeout_seconds: float = 2.0,
) -> None:
    data = {
        "type": event_type,
        "ts": _utc_now_iso(),
        "payload": payload,
    }
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        await client.post(url, json=data)


async def maybe_notify_webhook(*, event_type: str, payload: Dict[str, Any]) -> None:
    settings = get_settings()
    if not getattr(settings, "notify_webhook_enabled", False):
        return
    url = (getattr(settings, "notify_webhook_url", "") or "").strip()
    if not url:
        return

    try:
        await send_webhook_notification(event_type=event_type, payload=payload, url=url)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.debug("Webhook notification failed: %s", exc)


def approval_payload(*, approval, connector_name: str = "") -> Dict[str, Any]:
    # Avoid leaking confirm tokens via notifications.
    return {
        "approval_id": int(getattr(approval, "id", 0) or 0),
        "connector_id": int(getattr(approval, "connector_id", 0) or 0),
        "connector_name": connector_name,
        "status": getattr(approval, "status", ""),
        "command_class": getattr(approval, "command_class", ""),
        "reason": getattr(approval, "reason", ""),
        "command_preview": _truncate(getattr(approval, "command_text", "") or ""),
    }
