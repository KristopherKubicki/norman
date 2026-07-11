import asyncio

from app.connectors.home_assistant_connector import HomeAssistantConnector


def test_process_incoming_home_assistant_event_normalizes_fields():
    connector = HomeAssistantConnector(config={})
    payload = {
        "event_type": "state_changed",
        "time_fired": "2026-02-19T03:00:00Z",
        "data": {
            "entity_id": "light.kitchen",
            "new_state": {
                "state": "on",
                "attributes": {"friendly_name": "Kitchen Light"},
            },
        },
    }

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )

    assert result["text"] == "Kitchen Light state_changed on"
    assert result["event_type"] == "state_changed"
    assert result["entity_id"] == "light.kitchen"
    assert result["entity_name"] == "Kitchen Light"
    assert result["state"] == "on"
    assert result["domain"] == "light"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "home_assistant"
    assert result["sensor_type"] == "home_automation"


def test_process_incoming_home_assistant_string_uses_passive_defaults():
    connector = HomeAssistantConnector(config={})

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming("automation fired")
    )

    assert result["text"] == "automation fired"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "home_assistant"
    assert result["sensor_type"] == "home_automation"
