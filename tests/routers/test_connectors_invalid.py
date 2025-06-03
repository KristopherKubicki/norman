from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_create_connector_invalid_type(test_app: TestClient, db: Session) -> None:
    payload = {"connector_type": "does_not_exist", "name": "bad", "config": {}}
    resp = test_app.post("/api/v1/connectors/", json=payload)
    assert resp.status_code == 400
