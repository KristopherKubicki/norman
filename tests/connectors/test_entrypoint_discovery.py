import sys
import types
from importlib.metadata import EntryPoint

from app.connectors import connector_utils
from app.connectors.base_connector import BaseConnector


class DummyConnector(BaseConnector):
    id = "dummy"
    name = "Dummy"

    def send_message(self, message):
        pass

    async def listen_and_process(self):  # pragma: no cover - dummy implementation
        pass

    async def process_incoming(
        self, message
    ):  # pragma: no cover - dummy implementation
        pass


# Create a module path for the entry point
module = types.ModuleType("tests.dummy_entry")
module.DummyConnector = DummyConnector
sys.modules["tests.dummy_entry"] = module


def test_discover_connectors_from_entry_points(monkeypatch):
    ep = EntryPoint(
        name="dummy",
        value="tests.dummy_entry:DummyConnector",
        group="norman.connectors",
    )
    monkeypatch.setattr(connector_utils, "connector_classes", {})
    monkeypatch.setattr(connector_utils.pkgutil, "iter_modules", lambda paths: [])
    monkeypatch.setattr(connector_utils.metadata, "entry_points", lambda **kw: [ep])

    connector_utils._discover_connectors()
    assert "dummy" in connector_utils.connector_classes
    assert connector_utils.connector_classes["dummy"] is DummyConnector
