import requests
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import crud
import app.app_routes as routes


class DummyResponse:
    def __init__(self, data=None, status=200):
        self._data = data or {}
        self.status_code = status

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("error")


def test_google_callback_success(monkeypatch, test_app: TestClient, db: Session):
    def fake_post(url, data=None):
        return DummyResponse({"id_token": "tok"})

    monkeypatch.setattr(routes.requests, "post", fake_post)
    monkeypatch.setattr(routes.jwt, "decode", lambda token, options=None: {"email": "g@example.com", "name": "GUser"})
    test_app.cookies.clear()
    resp = test_app.get("/auth/google/callback?code=abc", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.cookies.get("access_token")
    assert crud.user.get_user_by_email(db, "g@example.com")


def test_google_callback_missing_email(monkeypatch, test_app: TestClient, db: Session):
    def fake_post(url, data=None):
        return DummyResponse({"id_token": "tok"})

    monkeypatch.setattr(routes.requests, "post", fake_post)
    monkeypatch.setattr(routes.jwt, "decode", lambda token, options=None: {})
    test_app.cookies.clear()
    resp = test_app.get("/auth/google/callback?code=abc", follow_redirects=False)
    assert resp.status_code == 400


def test_microsoft_callback_success(monkeypatch, test_app: TestClient, db: Session):
    def fake_post(url, data=None):
        return DummyResponse({"id_token": "tok"})

    monkeypatch.setattr(routes.requests, "post", fake_post)
    monkeypatch.setattr(routes.jwt, "decode", lambda token, options=None: {"email": "m@example.com", "name": "MUser"})
    test_app.cookies.clear()
    resp = test_app.get("/auth/microsoft/callback?code=abc", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.cookies.get("access_token")
    assert crud.user.get_user_by_email(db, "m@example.com")


def test_microsoft_callback_missing_email(monkeypatch, test_app: TestClient, db: Session):
    def fake_post(url, data=None):
        return DummyResponse({"id_token": "tok"})

    monkeypatch.setattr(routes.requests, "post", fake_post)
    monkeypatch.setattr(routes.jwt, "decode", lambda token, options=None: {})
    test_app.cookies.clear()
    resp = test_app.get("/auth/microsoft/callback?code=abc", follow_redirects=False)
    assert resp.status_code == 400

