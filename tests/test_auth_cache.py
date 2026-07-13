import asyncio
from types import SimpleNamespace

from app.api import deps
from app.core.auth_cache import (
    cache_admin_exists,
    cache_user,
    clear_auth_caches,
    get_cached_admin_exists,
    get_cached_user,
    invalidate_user,
)
from app.models.user import User


def test_user_cache_round_trips_detached_snapshot():
    clear_auth_caches()
    user = User(
        id=7,
        username="normal",
        email="normal@example.com",
        password="hashed",
        is_superuser=True,
    )
    cached = cache_user(user)
    assert cached.email == user.email
    assert cached is not user

    restored = get_cached_user(user.email)
    assert restored is not None
    assert restored.email == user.email
    assert restored.is_superuser is True
    assert restored is not cached


def test_auth_cache_invalidation_and_admin_cache():
    clear_auth_caches()
    user = User(
        id=9,
        username="operator",
        email="operator@example.com",
        password="hashed",
        is_superuser=False,
    )
    cache_user(user)
    assert get_cached_user(user.email) is not None
    invalidate_user(user.email)
    assert get_cached_user(user.email) is None

    assert get_cached_admin_exists() is None
    cache_admin_exists(True)
    assert get_cached_admin_exists() is True


def test_console_runtime_service_token_auth_uses_cached_user(monkeypatch):
    clear_auth_caches()
    user = User(
        id=11,
        username="runtime",
        email="runtime@example.com",
        password="hashed",
        is_superuser=True,
    )
    cache_user(user)
    monkeypatch.setattr(deps.settings, "console_runtime_service_token", "runtime-token")
    monkeypatch.setattr(
        deps.settings,
        "console_runtime_service_user_email",
        "runtime@example.com",
    )

    def fail_db_lookup(*_args, **_kwargs):
        raise AssertionError("cached service-token auth should not query the DB")

    monkeypatch.setattr(deps, "get_user_by_email", fail_db_lookup)

    request = SimpleNamespace(cookies={})
    resolved = asyncio.run(
        deps.get_console_runtime_user(
            request,
            token="Bearer runtime-token",
            db=object(),
        )
    )

    assert resolved.email == user.email
    assert resolved is not user
