import types
import pytest
import app.connectors.amqp_connector as mod

class DummyChannel:
    def __init__(self):
        self.published = []
    def queue_declare(self, queue, durable=True):
        self.queue = queue
    def basic_publish(self, exchange="", routing_key=None, body=None):
        self.published.append((routing_key, body))

class DummyConnection:
    def __init__(self):
        self.channel_obj = DummyChannel()
    def channel(self):
        return self.channel_obj
    def close(self):
        self.closed = True


def test_send_message_success(monkeypatch):
    dummy = DummyConnection()
    stub = types.SimpleNamespace(
        BlockingConnection=lambda params: dummy,
        URLParameters=lambda url: url,
    )
    monkeypatch.setattr(mod, "pika", stub)
    connector = mod.AMQPConnector("amqp://", "q")
    connector.send_message("hi")
    assert dummy.channel_obj.published == [("q", b"hi")]


def test_send_message_no_library(monkeypatch):
    monkeypatch.setattr(mod, "pika", None)
    connector = mod.AMQPConnector("amqp://", "q")
    with pytest.raises(RuntimeError):
        connector.send_message("hi")
