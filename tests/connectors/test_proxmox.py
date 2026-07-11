import asyncio

from app.connectors.proxmox_connector import ProxmoxConnector


def test_process_incoming_proxmox_event_normalizes_fields():
    connector = ProxmoxConnector(config={})
    payload = {
        "cluster": "homelab",
        "node": "pve1",
        "vmid": 101,
        "name": "worker-1",
        "event": "vm_stop",
        "status": "stopped",
    }

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )

    assert result["text"] == "homelab pve1 worker-1 vm_stop stopped"
    assert result["cluster"] == "homelab"
    assert result["node"] == "pve1"
    assert result["vmid"] == 101
    assert result["guest"] == "worker-1"
    assert result["event_type"] == "vm_stop"
    assert result["status"] == "stopped"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "proxmox"
    assert result["sensor_type"] == "virtualization"


def test_process_incoming_proxmox_string_uses_passive_defaults():
    connector = ProxmoxConnector(config={})

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming("node maintenance mode")
    )

    assert result["text"] == "node maintenance mode"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "proxmox"
    assert result["sensor_type"] == "virtualization"
