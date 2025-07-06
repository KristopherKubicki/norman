import asyncio
import types
import pytest

import app.connectors.mqtt_connector as mqtt_connector


class DummyClient:
    def __init__(self):
        self.published = []
        self.connected = False
        self.disconnected = False

    def username_pw_set(self, username, password):
        self.user = username
        self.pw = password

    def connect(self, host, port):
        self.connected = True
        self.host = host
        self.port = port

    def publish(self, topic, message):
        self.published.append((topic, message))

    def disconnect(self):
        self.disconnected = True

    def subscribe(self, topic):
        self.subscribed = topic

    def loop_start(self):
        pass

    def loop_stop(self):
        pass


def test_send_message_success(monkeypatch):
    dummy = DummyClient()
    stub = types.SimpleNamespace(Client=lambda: dummy)
    monkeypatch.setattr(mqtt_connector, "mqtt", stub)
    connector = mqtt_connector.MQTTConnector(host="h", topic="t")
    asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert dummy.published == [("t", "hi")]
    assert dummy.disconnected


def test_send_message_no_library(monkeypatch):
    monkeypatch.setattr(mqtt_connector, "mqtt", None)
    connector = mqtt_connector.MQTTConnector(host="h")
    with pytest.raises(RuntimeError):
        asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
