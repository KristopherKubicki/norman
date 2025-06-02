from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app import crud
from app.schemas.connector import ConnectorCreate


def test_test_connector_endpoint(test_app: TestClient, db: Session, monkeypatch) -> None:
    connector = crud.connector.create(db, obj_in=ConnectorCreate(name="irc1", connector_type="irc", config={}))

    class DummyConnector:
        def is_connected(self):
            return True

    monkeypatch.setattr("app.app_routes.get_connector", lambda *a, **k: DummyConnector())

    resp = test_app.post(f"/api/connectors/{connector.id}/test")
    assert resp.status_code == 200
    assert resp.json()["status"] == "up"


def test_status_endpoint_uses_cache(test_app: TestClient, db: Session, monkeypatch) -> None:
    connector = crud.connector.create(db, obj_in=ConnectorCreate(name="irc1", connector_type="irc", config={}))

    class DummyConnector:
        def __init__(self):
            self.calls = 0

        def is_connected(self):
            self.calls += 1
            return True

    dummy_connector = DummyConnector()
    monkeypatch.setattr("app.app_routes.get_connector", lambda *a, **k: dummy_connector)

    class DummyRedis:
        def __init__(self):
            self.store = {}

        def get(self, key):
            return self.store.get(key)

        def setex(self, key, ttl, value):
            self.store[key] = value

    dummy_redis = DummyRedis()
    monkeypatch.setattr("app.app_routes.get_redis_client", lambda: dummy_redis)
    monkeypatch.setattr("app.app_routes._refresh_status", lambda *a, **k: None)

    resp1 = test_app.get(f"/api/connectors/{connector.id}/status")
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "up"
    assert "timestamp" in resp1.json()
    assert dummy_connector.calls == 1

    resp2 = test_app.get(f"/api/connectors/{connector.id}/status")
    assert resp2.status_code == 200
    assert dummy_connector.calls == 1  # second call served from cache
