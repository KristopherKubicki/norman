"""Connector for workstation activity monitor events.

This adapter normalizes local desktop activity into passive operator-state
signals that Norman can merge with broader presence feeds.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .webhook_only_connector import WebhookOnlyConnector


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _boolish(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    lowered = _clean(value).lower()
    if not lowered:
        return None
    if lowered in {"1", "true", "yes", "y", "on", "active", "awake", "open"}:
        return True
    if lowered in {"0", "false", "no", "n", "off", "idle", "inactive", "locked"}:
        return False
    return None


def _intish(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


class ActivityMonitorConnector(WebhookOnlyConnector):
    id = "activity_monitor"
    name = "Activity Monitor"

    async def process_incoming(self, message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            normalized = await super().process_incoming(message)
            normalized.setdefault("signal_class", "passive")
            normalized.setdefault("passive_source", "activity_monitor")
            normalized.setdefault("sensor_type", "activity")
            return normalized

        host = _clean(
            message.get("host")
            or message.get("hostname")
            or message.get("machine")
            or message.get("device")
            or message.get("source")
        )
        zone = _clean(
            message.get("zone")
            or message.get("presence_zone")
            or (self.config or {}).get("zone")
        )
        site = _clean(message.get("site") or (self.config or {}).get("site"))

        user_active = _boolish(message.get("userActive", message.get("user_active")))
        screen_awake = _boolish(message.get("screenAwake", message.get("screen_awake")))
        session_locked = _boolish(
            message.get("sessionLocked", message.get("session_locked"))
        )
        display_idle_seconds = _intish(
            message.get(
                "displayIdleSeconds",
                message.get("display_idle_seconds", message.get("idleSeconds")),
            )
        )

        if (
            user_active is None
            and screen_awake is not None
            and display_idle_seconds is not None
        ):
            user_active = bool(screen_awake and display_idle_seconds < 90)

        state = _clean(message.get("state") or message.get("status"))
        if not state:
            if session_locked:
                state = "locked"
            elif user_active:
                state = "active"
            elif screen_awake is False:
                state = "sleeping"
            elif display_idle_seconds is not None:
                state = "idle"
            else:
                state = "activity"

        text_parts = [part for part in (host, zone, state) if part]
        text = _clean(message.get("text") or message.get("summary")) or " ".join(
            text_parts
        )
        if not text:
            text = "activity monitor event"

        summary_parts = ["activity"]
        if host:
            summary_parts.append(host)
        if zone:
            summary_parts.append(zone)
        summary_parts.append(state)
        if display_idle_seconds is not None:
            summary_parts.append(f"idle {display_idle_seconds}s")
        summary = " • ".join(part for part in summary_parts if part)

        return {
            "text": text,
            "text_summary": summary,
            "host": host or None,
            "zone": zone or None,
            "site": site or None,
            "state": state,
            "user_active": user_active,
            "screen_awake": screen_awake,
            "session_locked": session_locked,
            "display_idle_seconds": display_idle_seconds,
            "signal_class": "passive",
            "passive_source": "activity_monitor",
            "sensor_type": "activity",
        }
