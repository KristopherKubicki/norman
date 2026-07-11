from typing import Dict, List
import time
import asyncio
import sys
import os
import weakref
from fastapi import Request, Response
from app.core.config import get_settings


class RateLimiter:
    """Simple in-memory IP based rate limiter middleware."""

    def __init__(self) -> None:
        settings = get_settings()
        self.max_requests = settings.rate_limit_requests
        self.window = settings.rate_limit_window_seconds
        disable_env = os.environ.get("DISABLE_RATE_LIMIT", "").lower()
        self.disabled = settings.debug or disable_env in {"1", "true", "yes"}
        if "pytest" in sys.modules:
            self.max_requests = 10000
        self.requests: Dict[str, List[float]] = {}
        self._locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        lock = self._locks.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[loop] = lock
        return lock

    async def __call__(self, request: Request, call_next):
        # Only rate-limit mutating requests. Read traffic (page loads, icons,
        # catalog fetches, polling) should stay responsive and never trip 429s.
        method = request.scope.get("method", "GET").upper()
        if method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)

        # Never rate-limit static assets.
        try:
            path = request.url.path
        except Exception:
            path = ""
        if path.startswith("/static/") or path == "/favicon.ico":
            return await call_next(request)

        if self.disabled or self.max_requests <= 0:
            return await call_next(request)
        identifier = request.client.host if request.client else "unknown"
        now = time.time()
        async with self._get_lock():
            timestamps = [
                t for t in self.requests.get(identifier, []) if now - t < self.window
            ]
            if len(timestamps) >= self.max_requests:
                return Response(
                    status_code=429,
                    content="Too Many Requests",
                    headers={"Retry-After": str(int(self.window))},
                )
            timestamps.append(now)
            self.requests[identifier] = timestamps
        return await call_next(request)
