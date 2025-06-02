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
