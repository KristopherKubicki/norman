import asyncio

from app.connectors.ntfy_connector import NtfyConnector


def test_process_incoming_ntfy_event_normalizes_fields():
    connector = NtfyConnector(config={})
    payload = {
        "topic": "ops",
        "title": "Deploy",
        "message": "Deploy complete",
        "priority": 3,
        "tags": ["rocket"],
    }

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )

    assert result["text"] == "Deploy complete"
    assert result["topic"] == "ops"
    assert result["title"] == "Deploy"
    assert result["priority"] == 3
    assert result["tags"] == ["rocket"]
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "ntfy"
    assert result["sensor_type"] == "push_notifications"


def test_process_incoming_ntfy_string_uses_passive_defaults():
    connector = NtfyConnector(config={})

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming("ntfy ping")
    )

    assert result["text"] == "ntfy ping"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "ntfy"
    assert result["sensor_type"] == "push_notifications"
