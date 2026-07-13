from __future__ import annotations

from app import crud
from app.core.encryption import EncryptionManager
from app.models import SecretStashItem
from app.schemas.channel import ChannelCreate
from app.schemas.connector import ConnectorCreate
from app.schemas.user import UserCreate


def _ensure_test_user(db):
    user = crud.user.get_user_by_email(db, "test@example.com")
    if user:
        return user
    return crud.user.create_user(
        db,
        user=UserCreate(
            email="test@example.com",
            username="test_user",
            password="pass123",
        ),
    )


def _create_channel(db, *, name: str):
    user = _ensure_test_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name=f"{name}-connector",
            connector_type="sample",
            config={},
        ),
        user_id=user.id,
    )
    channel = crud.channel.create(
        db,
        obj_in=ChannelCreate(name=name, connector_id=connector.id),
    )
    return channel


def test_secret_stash_create_returns_pointer_and_encrypts_value(test_app, db):
    channel = _create_channel(db, name="secret-stash-create")

    response = test_app.post(
        "/api/v1/keys/stash",
        json={
            "channel_id": channel.id,
            "label": "camera password",
            "value": "super-secret-value",
            "ttl_seconds": 1800,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["channel_id"] == channel.id
    assert payload["label"] == "camera password"
    assert payload["status"] == "active"
    assert payload["pointer"].startswith("norman-secret://stash/")
    assert payload["prompt_reference"] == f"Secret pointer: {payload['pointer']}"
    assert "camera password" not in payload["prompt_reference"]
    assert "super-secret-value" not in payload["masked_preview"]

    db.expire_all()
    item = db.query(SecretStashItem).filter(SecretStashItem.id == payload["id"]).first()
    assert item is not None
    assert item.encrypted_value != "super-secret-value"
    assert EncryptionManager().decrypt(item.encrypted_value) == "super-secret-value"


def test_secret_stash_list_filters_by_channel_and_revoke(test_app, db):
    first_channel = _create_channel(db, name="secret-stash-list-one")
    second_channel = _create_channel(db, name="secret-stash-list-two")

    first = test_app.post(
        "/api/v1/keys/stash",
        json={
            "channel_id": first_channel.id,
            "label": "camera token",
            "value": "camera-token-value",
        },
    )
    assert first.status_code == 201
    second = test_app.post(
        "/api/v1/keys/stash",
        json={
            "channel_id": second_channel.id,
            "label": "router token",
            "value": "router-token-value",
        },
    )
    assert second.status_code == 201

    listed = test_app.get(f"/api/v1/keys/stash?channel_id={first_channel.id}")
    assert listed.status_code == 200
    payload = listed.json()
    assert len(payload) == 1
    assert payload[0]["label"] == "camera token"

    revoke = test_app.post(f"/api/v1/keys/stash/{first.json()['id']}/revoke")
    assert revoke.status_code == 200
    assert revoke.json()["status"] == "revoked"

    listed_after = test_app.get(f"/api/v1/keys/stash?channel_id={first_channel.id}")
    assert listed_after.status_code == 200
    assert listed_after.json() == []


def test_secret_stash_rejects_unknown_channel(test_app):
    response = test_app.post(
        "/api/v1/keys/stash",
        json={
            "channel_id": 999999,
            "label": "unknown",
            "value": "super-secret-value",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Channel not found"
