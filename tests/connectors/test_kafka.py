import types
import pytest
import app.connectors.kafka_connector as mod

class DummyProducer:
    def __init__(self):
        self.messages = []
    def produce(self, topic, value=None):
        self.messages.append((topic, value))
    def flush(self):
        pass


def test_send_message_success(monkeypatch):
    monkeypatch.setattr(mod, "Producer", lambda conf: DummyProducer())
    connector = mod.KafkaConnector(bootstrap_servers="s", topic="t")
    assert connector.send_message("hi") == "ok"


def test_send_message_no_library(monkeypatch):
    monkeypatch.setattr(mod, "Producer", None)
    connector = mod.KafkaConnector()
    with pytest.raises(RuntimeError):
        connector.send_message("hi")
