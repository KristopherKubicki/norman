import asyncio

from app.connectors.frigate_connector import FrigateConnector


def test_process_incoming_frigate_event_normalizes_fields():
    connector = FrigateConnector(config={})
    payload = {
        "type": "new",
        "after": {
            "id": "evt-1",
            "camera": "front",
            "label": "person",
            "score": 0.91,
            "entered_zones": ["driveway"],
        },
    }

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )

    assert result["text"] == "front new person driveway"
    assert result["event_type"] == "new"
    assert result["camera"] == "front"
    assert result["zone"] == "driveway"
    assert result["label"] == "person"
    assert result["score"] == 0.91
    assert result["event_id"] == "evt-1"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "frigate"
    assert result["sensor_type"] == "vision"


def test_process_incoming_frigate_string_uses_passive_defaults():
    connector = FrigateConnector(config={})

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming("motion detected")
    )

    assert result["text"] == "motion detected"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "frigate"
    assert result["sensor_type"] == "vision"
