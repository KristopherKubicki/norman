import asyncio

from app.connectors.pfsense_opnsense_connector import PfSenseOPNsenseConnector


def test_process_incoming_firewall_event_normalizes_fields():
    connector = PfSenseOPNsenseConnector(config={})
    payload = {
        "firewall": "edge-gw",
        "event": "firewall_log",
        "action": "block",
        "src_ip": "10.0.0.10",
        "dst_ip": "8.8.8.8",
        "proto": "tcp",
        "rule_id": "102",
    }

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )

    assert result["text"] == "edge-gw firewall_log block tcp 10.0.0.10 -> 8.8.8.8"
    assert result["firewall"] == "edge-gw"
    assert result["event_type"] == "firewall_log"
    assert result["action"] == "block"
    assert result["src_ip"] == "10.0.0.10"
    assert result["dst_ip"] == "8.8.8.8"
    assert result["protocol"] == "tcp"
    assert result["rule"] == "102"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "pfsense_opnsense"
    assert result["sensor_type"] == "firewall"


def test_process_incoming_firewall_string_uses_passive_defaults():
    connector = PfSenseOPNsenseConnector(config={})

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming("vpn tunnel down")
    )

    assert result["text"] == "vpn tunnel down"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "pfsense_opnsense"
    assert result["sensor_type"] == "firewall"
