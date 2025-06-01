from app.connectors.broadcast_connector import BroadcastConnector
from app.connectors.base_connector import BaseConnector

class DummyConnector(BaseConnector):
    def __init__(self):
        super().__init__()
        self.sent = []

    def send_message(self, message):
        self.sent.append(message)

    async def listen_and_process(self):
        return None

    async def process_incoming(self, message):
        return message

    def is_connected(self):
        return True


def test_send_message(monkeypatch):
    instances = {"a": DummyConnector(), "b": DummyConnector()}

    def fake_get_connector(name):
        return instances[name]

    import app.connectors.connector_utils as cu
    monkeypatch.setattr(cu, "get_connector", fake_get_connector)
    monkeypatch.setitem(cu.connector_classes, "a", DummyConnector)
    monkeypatch.setitem(cu.connector_classes, "b", DummyConnector)
    connector = BroadcastConnector("a,b")
    connector.send_message("hi")
    assert instances["a"].sent == ["hi"]
    assert instances["b"].sent == ["hi"]
    assert connector.is_connected() is True
