import asyncio

from app.connectors.arp_connector import ARPConnector


def test_process_incoming_dict_sets_passive_metadata():
    connector = ARPConnector(listen_interface="eth0")
    payload = {
        "src_ip": "10.0.0.2",
        "src_mac": "aa:bb:cc:dd:ee:ff",
        "dst_ip": "10.0.0.1",
        "op": "who-has",
    }

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )

    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "arp"
    assert "ARP who-has" in result["text"]


def test_send_message_is_noop():
    connector = ARPConnector()
    assert connector.send_message("hi") is None
