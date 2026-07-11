import threading
import time
from typing import Optional

from app.models.user import User

_CACHE_TTL_SECONDS = 30.0
_ADMIN_CACHE_TTL_SECONDS = 60.0

_cache_lock = threading.Lock()
_user_cache: dict[str, tuple[float, dict[str, object]]] = {}
_admin_exists_cache: tuple[float, Optional[bool]] = (0.0, None)


def _snapshot_user(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "password": user.password,
        "is_superuser": user.is_superuser,
    }


def _restore_user(snapshot: dict[str, object]) -> User:
    return User(**snapshot)


def get_cached_user(email: str) -> Optional[User]:
    now = time.monotonic()
    with _cache_lock:
        cached = _user_cache.get(email)
        if not cached:
            return None
        expires_at, snapshot = cached
        if expires_at <= now:
            _user_cache.pop(email, None)
            return None
        return _restore_user(snapshot)


def cache_user(user: User) -> User:
    snapshot = _snapshot_user(user)
    with _cache_lock:
        _user_cache[user.email] = (
            time.monotonic() + _CACHE_TTL_SECONDS,
            snapshot,
        )
    return _restore_user(snapshot)


def invalidate_user(email: str) -> None:
    with _cache_lock:
        _user_cache.pop(email, None)


def get_cached_admin_exists() -> Optional[bool]:
    now = time.monotonic()
    with _cache_lock:
        expires_at, value = _admin_exists_cache
        if value is None or expires_at <= now:
            return None
        return value


def cache_admin_exists(value: bool) -> bool:
    global _admin_exists_cache
    with _cache_lock:
        _admin_exists_cache = (time.monotonic() + _ADMIN_CACHE_TTL_SECONDS, value)
    return value


def clear_auth_caches() -> None:
    global _admin_exists_cache
    with _cache_lock:
        _user_cache.clear()
        _admin_exists_cache = (0.0, None)
