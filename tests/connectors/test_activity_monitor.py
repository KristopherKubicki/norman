import asyncio

from app.connectors.activity_monitor_connector import ActivityMonitorConnector


def test_process_incoming_activity_monitor_event_normalizes_fields():
    connector = ActivityMonitorConnector(config={"site": "knox", "zone": "office"})
    payload = {
        "host": "hal",
        "userActive": True,
        "screenAwake": True,
        "displayIdleSeconds": 14,
        "sessionLocked": False,
    }

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )

    assert result["text"] == "hal office active"
    assert result["host"] == "hal"
    assert result["zone"] == "office"
    assert result["site"] == "knox"
    assert result["state"] == "active"
    assert result["user_active"] is True
    assert result["screen_awake"] is True
    assert result["session_locked"] is False
    assert result["display_idle_seconds"] == 14
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "activity_monitor"
    assert result["sensor_type"] == "activity"


def test_process_incoming_non_dict_uses_webhook_fallback():
    connector = ActivityMonitorConnector(config={})

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming("desktop idle")
    )

    assert result["text"] == "desktop idle"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "activity_monitor"
    assert result["sensor_type"] == "activity"
