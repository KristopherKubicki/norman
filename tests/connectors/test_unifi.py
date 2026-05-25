import asyncio

from app.connectors.unifi_connector import UnifiConnector


def test_process_incoming_unifi_event_normalizes_fields():
    connector = UnifiConnector(config={})
    payload = {
        "event": "device_offline",
        "site": "home",
        "severity": "critical",
        "device": {"name": "AP-LivingRoom"},
        "message": "AP offline",
    }

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )

    assert result["text"] == "AP offline"
    assert result["event_type"] == "device_offline"
    assert result["site"] == "home"
    assert result["severity"] == "critical"
    assert result["device"] == "AP-LivingRoom"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "unifi"
    assert result["sensor_type"] == "network"


def test_process_incoming_unifi_string_uses_passive_defaults():
    connector = UnifiConnector(config={})

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming("switch link recovered")
    )

    assert result["text"] == "switch link recovered"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "unifi"
    assert result["sensor_type"] == "network"
