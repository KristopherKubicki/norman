import asyncio
import types
import pytest

import app.connectors.aws_iot_core_connector as mod


class DummyClient:
    def __init__(self):
        self.published = []

    def publish(self, topic=None, qos=None, payload=None):
        self.published.append((topic, qos, payload))
        return {"ok": True}


def test_send_message_success(monkeypatch):
    stub = types.SimpleNamespace(
        client=lambda service, region_name=None, endpoint_url=None: DummyClient()
    )
    monkeypatch.setattr(mod, "boto3", stub)
    connector = mod.AWSIoTCoreConnector(region="us", topic="t")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == {"ok": True}


def test_send_message_no_boto3(monkeypatch):
    monkeypatch.setattr(mod, "boto3", None)
    connector = mod.AWSIoTCoreConnector(region="us", topic="t")
    with pytest.raises(RuntimeError):
        asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))


def test_listen_requires_mqtt(monkeypatch):
    monkeypatch.setattr(mod, "mqtt", None)
    connector = mod.AWSIoTCoreConnector(region="us", topic="t", endpoint="https://e")
    with pytest.raises(RuntimeError):
        asyncio.get_event_loop().run_until_complete(connector.listen_and_process())
