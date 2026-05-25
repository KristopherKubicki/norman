import asyncio

from app.connectors.hubitat_connector import HubitatConnector


def test_process_incoming_hubitat_event_normalizes_fields():
    connector = HubitatConnector(config={})
    payload = {
        "displayName": "Kitchen Motion",
        "name": "motion",
        "value": "active",
        "deviceId": "42",
        "unit": "",
        "source": "DEVICE",
        "locationId": "home",
    }

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )

    assert result["text"] == "Kitchen Motion motion active"
    assert result["device"] == "Kitchen Motion"
    assert result["device_id"] == "42"
    assert result["attribute"] == "motion"
    assert result["value"] == "active"
    assert result["source"] == "DEVICE"
    assert result["location"] == "home"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "hubitat"
    assert result["sensor_type"] == "home_automation"


def test_process_incoming_non_dict_uses_webhook_fallback():
    connector = HubitatConnector(config={})

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming("switch changed")
    )

    assert result["text"] == "switch changed"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "hubitat"
    assert result["sensor_type"] == "home_automation"
