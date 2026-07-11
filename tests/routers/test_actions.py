from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import crud
from app.crud.user import create_user, get_user_by_email
from app.schemas.channel import ChannelCreate
from app.schemas.connector import ConnectorCreate
from app.schemas.filter import FilterCreate
from app.schemas.user import UserCreate


def test_actions_router_crud(test_app: TestClient, db: Session) -> None:
    user = get_user_by_email(db, email="test@example.com")
    if user is None:
        user = create_user(
            db,
            UserCreate(
                email="test@example.com", username="test_user", password="pass123"
            ),
        )

    connector = crud.connector.create(
        db,
        ConnectorCreate(name="test", connector_type="webhook", config={}),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db, ChannelCreate(name="chan", connector_id=connector.id)
    )
    channel_filter = crud.channel_filter.create(
        db,
        FilterCreate(channel_id=channel.id, regex=".*", description="all"),
    )
    channel_id = channel.id
    filter_id = channel_filter.id
    # Free the shared in-memory SQLite connection before the API request thread runs.
    db.close()

    payload = {
        "channel_filter_id": filter_id,
        "prompt": "hi",
        "reply_channel_id": channel_id,
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
