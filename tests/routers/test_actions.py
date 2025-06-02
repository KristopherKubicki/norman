from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_actions_router_crud(test_app: TestClient, db: Session) -> None:
    payload = {
        "channel_filter_id": 1,
        "prompt": "hi",
        "reply_channel_id": 1,
        "execution_order": 1,
    }
    resp = test_app.post("/api/v1/actions/", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    action_id = data["id"]

    resp = test_app.get(f"/api/v1/actions/{action_id}")
    assert resp.status_code == 200
    assert resp.json()["prompt"] == payload["prompt"]

    update = {
        "channel_filter_id": 1,
        "prompt": "bye",
        "reply_channel_id": 1,
        "execution_order": 2,
    }
    resp = test_app.put(f"/api/v1/actions/{action_id}", json=update)
    assert resp.status_code == 200
    assert resp.json()["prompt"] == update["prompt"]

    resp = test_app.delete(f"/api/v1/actions/{action_id}")
    assert resp.status_code == 200

    resp = test_app.get(f"/api/v1/actions/{action_id}")
    assert resp.status_code == 404
