from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_connectors_router_crud(test_app: TestClient, db: Session) -> None:
    payload = {"connector_type": "irc", "name": "c1", "config": {}}
    resp = test_app.post("/api/v1/connectors/connectors/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    connector_id = data["id"]

    resp = test_app.get("/api/v1/connectors/connectors/")
    assert resp.status_code == 200
    assert any(c["id"] == connector_id for c in resp.json())

    update = {"connector_type": "irc", "name": "c2", "config": {}}
    resp = test_app.put(
        f"/api/v1/connectors/connectors/{connector_id}", json=update
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == update["name"]

    resp = test_app.delete(f"/api/v1/connectors/connectors/{connector_id}")
    assert resp.status_code == 200

    resp = test_app.get(f"/api/v1/connectors/connectors/{connector_id}")
    assert resp.status_code == 404
