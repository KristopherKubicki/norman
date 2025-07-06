from app.initial_setup import create_initial_admin_user
from app.core import config


class DummyDB:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_create_initial_admin_user_creates(monkeypatch):
    db = DummyDB()
    monkeypatch.setattr("app.initial_setup.SessionLocal", lambda: db)

    calls = {}

    def fake_is_admin_user_exists(session):
        assert session is db
        calls["checked"] = True
        return False

    def fake_create_admin_user(session, email, password, username):
        calls["created"] = (email, password, username)

    monkeypatch.setattr(
        "app.initial_setup.is_admin_user_exists", fake_is_admin_user_exists
    )
    monkeypatch.setattr("app.initial_setup.create_admin_user", fake_create_admin_user)

    create_initial_admin_user()

    assert calls.get("checked") is True
    assert calls.get("created") == (
        config.settings.initial_admin_email,
        config.settings.initial_admin_password,
        config.settings.initial_admin_username,
    )
    assert db.closed


def test_create_initial_admin_user_skips_if_exists(monkeypatch):
    db = DummyDB()
    monkeypatch.setattr("app.initial_setup.SessionLocal", lambda: db)

    def fake_is_admin_user_exists(session):
        assert session is db
        return True

    called = False

    def fake_create_admin_user(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "app.initial_setup.is_admin_user_exists", fake_is_admin_user_exists
    )
    monkeypatch.setattr("app.initial_setup.create_admin_user", fake_create_admin_user)

    create_initial_admin_user()

    assert called is False
    assert db.closed
