from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_console_targets_router_crud(test_app: TestClient, db: Session) -> None:
    payload = {
        "name": "Norman Pane",
        "kind": "tmux",
        "socket_path": "",
        "session_name": "norman",
        "target": "norman:0.0",
    }
    resp = test_app.post("/api/v1/console_targets/", json=payload)
    assert resp.status_code == 201
    created = resp.json()
    target_id = created["id"]
    assert created["name"] == payload["name"]
    assert created["target"] == payload["target"]

    resp = test_app.get("/api/v1/console_targets/")
    assert resp.status_code == 200
    assert any(t["id"] == target_id for t in resp.json())

    update = {"name": "Renamed Pane"}
    resp = test_app.put(f"/api/v1/console_targets/{target_id}", json=update)
    assert resp.status_code == 200
    assert resp.json()["name"] == update["name"]

    resp = test_app.delete(f"/api/v1/console_targets/{target_id}")
    assert resp.status_code == 200

    resp = test_app.get("/api/v1/console_targets/")
    assert resp.status_code == 200
    assert all(t["id"] != target_id for t in resp.json())


def test_console_targets_enforces_unique_name_per_user(test_app: TestClient) -> None:
    payload = {
        "name": "Duplicate",
        "kind": "tmux",
        "socket_path": "",
        "session_name": "norman",
        "target": "norman:0.0",
    }
    resp = test_app.post("/api/v1/console_targets/", json=payload)
    assert resp.status_code == 201

    resp = test_app.post("/api/v1/console_targets/", json=payload)
    assert resp.status_code == 409
