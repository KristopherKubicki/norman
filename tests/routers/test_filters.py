import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_filters_router_crud(test_app: TestClient, db: Session) -> None:
    payload = {"channel_id": 1, "regex": r"\\btest\\b", "description": "desc"}
    resp = test_app.post("/api/v1/filters/", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    filter_id = data["id"]
    assert data["regex"] == payload["regex"]

    resp = test_app.get("/api/v1/filters/")
    assert resp.status_code == 200
    assert any(f["id"] == filter_id for f in resp.json())

    update = {"channel_id": 1, "regex": r"\\bupd\\b", "description": "upd"}
    resp = test_app.put(f"/api/v1/filters/{filter_id}", json=update)
    assert resp.status_code == 200
    assert resp.json()["regex"] == update["regex"]

    resp = test_app.delete(f"/api/v1/filters/{filter_id}")
    assert resp.status_code == 200
    resp = test_app.get("/api/v1/filters/")
    ids = [f["id"] for f in resp.json()]
    assert filter_id not in ids
