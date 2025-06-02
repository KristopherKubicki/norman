import asyncio
import types
import pytest

import app.connectors.aws_eventbridge_connector as mod

class DummyClient:
    def __init__(self):
        self.entries = None
        self.ok = True
    def put_events(self, Entries=None):
        self.entries = Entries
        return {"ok": True}
    def describe_event_bus(self, Name=None):
        if self.ok:
            return {}
        raise Exception("error")


def test_send_message_success(monkeypatch):
    stub = types.SimpleNamespace(client=lambda service, region_name=None: DummyClient())
    monkeypatch.setattr(mod, "boto3", stub)
    connector = mod.AWSEventBridgeConnector(region="us", event_bus_name="bus")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message({"a":1}))
    assert result == {"ok": True}


def test_send_message_no_boto3(monkeypatch):
    monkeypatch.setattr(mod, "boto3", None)
    connector = mod.AWSEventBridgeConnector(region="us", event_bus_name="bus")
    with pytest.raises(RuntimeError):
        asyncio.get_event_loop().run_until_complete(connector.send_message({}))


def test_is_connected_success(monkeypatch):
    client = DummyClient()
    stub = types.SimpleNamespace(client=lambda service, region_name=None: client)
    monkeypatch.setattr(mod, "boto3", stub)
    connector = mod.AWSEventBridgeConnector(region="us", event_bus_name="bus")
    assert connector.is_connected()


def test_is_connected_error(monkeypatch):
    client = DummyClient()
    client.ok = False
    stub = types.SimpleNamespace(client=lambda service, region_name=None: client)
    monkeypatch.setattr(mod, "boto3", stub)
    connector = mod.AWSEventBridgeConnector(region="us", event_bus_name="bus")
    assert not connector.is_connected()

