from app import crud
from app.schemas.connector import ConnectorCreate
from app.schemas.user import UserCreate
from app.services.connector_oauth import PendingConnectorOAuth


def _ensure_user(db):
    user = crud.user.get_user_by_email(db, "test@example.com")
    if not user:
        user = crud.user.create_user(
            db,
            user=UserCreate(
                email="test@example.com",
                username="test_user",
                password="pass123",
            ),
        )
    return user


def test_start_connector_oauth_redirects(test_app, db, monkeypatch):
    user = _ensure_user(db)

    monkeypatch.setattr(
        "app.api.api_v1.routers.connectors_crud.resolve_oauth_binding",
        lambda connector_type, provider=None: {
            "provider": "google",
            "token_field": "token",
            "scopes": ["openid", "email"],
        },
    )
    monkeypatch.setattr(
        "app.api.api_v1.routers.connectors_crud.create_pending_state",
        lambda **kwargs: "state_abc",
    )

    resp = test_app.get(
        "/api/v1/connectors/oauth/start?connector_type=slack&provider=google"
    )
    assert resp.status_code == 303
    assert "accounts.google.com/o/oauth2/v2/auth" in resp.headers["location"]
    assert "state=state_abc" in resp.headers["location"]

    connectors = crud.connector.get_multi_by_user(db, user.id)
    assert any(conn.connector_type == "slack" for conn in connectors)


def test_google_oauth_callback_updates_connector(test_app, db, monkeypatch):
    user = _ensure_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="Slack OAuth",
            connector_type="slack",
            config={},
        ),
        user_id=user.id,
    )

    monkeypatch.setattr(
        "app.api.api_v1.routers.connectors_crud.consume_pending_state",
        lambda state, user_id: PendingConnectorOAuth(
            state=state,
            user_id=user.id,
            connector_id=connector.id,
            connector_type="slack",
            provider="google",
            token_field="token",
            created_at=0.0,
        ),
    )

    class DummyResp:
        ok = True

        @staticmethod
        def json():
            return {
                "access_token": "token_123",
                "refresh_token": "refresh_456",
                "expires_in": 3600,
            }

    monkeypatch.setattr(
        "app.api.api_v1.routers.connectors_crud.requests.post",
        lambda *args, **kwargs: DummyResp(),
    )

    resp = test_app.get("/api/v1/connectors/oauth/callback/google?code=ok&state=s1")
    assert resp.status_code == 303
    assert "/connectors.html?oauth=success" in resp.headers["location"]

    check = test_app.get(f"/api/v1/connectors/{connector.id}")
    assert check.status_code == 200
    data = check.json()
    assert data["config"]["token"] == "token_123"
    assert data["config"]["oauth_provider"] == "google"


def test_disconnect_connector_oauth_clears_oauth_fields(test_app, db):
    user = _ensure_user(db)
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="OAuth Connector",
            connector_type="slack",
            config={
                "token": "oauth_token",
                "channel_id": "C123",
                "oauth_provider": "google",
                "oauth_connected_at": "2026-01-01T00:00:00+00:00",
                "oauth_refresh_token": "refresh",
            },
        ),
        user_id=user.id,
    )

    resp = test_app.delete(f"/api/v1/connectors/{connector.id}/oauth")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "disconnected"
    assert payload["connector_id"] == connector.id

    check = test_app.get(f"/api/v1/connectors/{connector.id}")
    assert check.status_code == 200
    data = check.json()
    assert data["config"].get("oauth_provider") in (None, "")
    assert data["config"].get("oauth_connected_at") in (None, "")
    assert data["config"]["channel_id"] == "C123"
