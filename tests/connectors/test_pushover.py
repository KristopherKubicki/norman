import asyncio

from app.connectors.pushover_connector import PushoverConnector


def test_process_incoming_pushover_event_normalizes_fields():
    connector = PushoverConnector(config={})
    payload = {
        "title": "Disk Alert",
        "message": "Disk usage 92%",
        "priority": 1,
        "user": "u1",
        "device": "phone",
    }

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )

    assert result["text"] == "Disk usage 92%"
    assert result["title"] == "Disk Alert"
    assert result["priority"] == 1
    assert result["user"] == "u1"
    assert result["device"] == "phone"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "pushover"
    assert result["sensor_type"] == "push_notifications"


def test_process_incoming_pushover_string_uses_passive_defaults():
    connector = PushoverConnector(config={})

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming("push received")
    )

    assert result["text"] == "push received"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "pushover"
    assert result["sensor_type"] == "push_notifications"
