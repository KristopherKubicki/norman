import asyncio
import types
import pytest
import app.connectors.aprs_connector as mod

class DummyIS:
    def __init__(self):
        self.sent = []
        self.closed = False
    def connect(self):
        pass
    def sendall(self, msg):
        self.sent.append(msg)
    def close(self):
        self.closed = True
    def __iter__(self):
        return iter([])


def test_send_message_success(monkeypatch):
    dummy = DummyIS()
    stub = types.SimpleNamespace(IS=lambda *a, **k: dummy)
    monkeypatch.setattr(mod, "aprslib", stub)
    connector = mod.APRSConnector("host")
    asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert dummy.sent == ["hi"]
    assert dummy.closed


def test_send_message_no_library(monkeypatch):
    monkeypatch.setattr(mod, "aprslib", None)
    connector = mod.APRSConnector("host")
    with pytest.raises(RuntimeError):
        asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
