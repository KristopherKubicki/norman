import app.connectors.redis_pubsub_connector as mod
import types
import pytest

class DummyRedis:
    def __init__(self):
        self.published = []
    def publish(self, channel, message):
        self.published.append((channel, message))


def test_send_message_success(monkeypatch):
    monkeypatch.setattr(mod, "redis", types.SimpleNamespace(Redis=lambda host=None, port=None: DummyRedis()))
    connector = mod.RedisPubSubConnector(host="h", port=1, channel="c")
    connector.send_message("hi")
    assert connector._client.published == [("c", "hi")]


def test_send_message_no_library(monkeypatch):
    monkeypatch.setattr(mod, "redis", None)
    connector = mod.RedisPubSubConnector()
    with pytest.raises(RuntimeError):
        connector.send_message("hi")
