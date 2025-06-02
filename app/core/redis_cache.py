try:
    import redis
except ImportError:  # pragma: no cover - optional dependency
    redis = None

from app.core.config import settings

_redis_client = None


def get_redis_client():
    """Return a cached Redis client instance or ``None`` if unavailable."""
    global _redis_client
    if not redis:
        return None
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            decode_responses=True,
        )
    return _redis_client


def set_redis_client(client):
    """Override the global Redis client (used in tests)."""
    global _redis_client
    _redis_client = client
