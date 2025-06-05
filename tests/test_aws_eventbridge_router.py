from fastapi.testclient import TestClient
from app.api.api_v1.routers.connectors import aws_eventbridge as eventbridge_router
from app.core.test_settings import test_settings


def test_get_eventbridge_connector_uses_settings():
    connector = eventbridge_router.get_eventbridge_connector(test_settings)
    assert connector.region == test_settings.aws_eventbridge_region
    assert connector.event_bus_name == test_settings.aws_eventbridge_event_bus_name


def test_process_eventbridge_update(monkeypatch, test_app: TestClient):
    received = {}

    class DummyConnector:
        def __init__(self, region: str, event_bus_name: str, config=None):
            self.region = region
            self.event_bus_name = event_bus_name

        def process_incoming(self, payload):
            received["payload"] = payload

    monkeypatch.setattr(eventbridge_router, "AWSEventBridgeConnector", DummyConnector)
    resp = test_app.post(
        "/api/v1/connectors/aws_eventbridge/webhooks/eventbridge",
        json={"msg": "hi"},
    )
    assert resp.status_code == 200
    assert received["payload"] == {"msg": "hi"}
