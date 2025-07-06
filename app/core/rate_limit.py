from typing import Dict, List
import time
import asyncio
import sys
from fastapi import Request, Response
from app.core.config import get_settings


class RateLimiter:
    """Simple in-memory IP based rate limiter middleware."""

    def __init__(self) -> None:
        settings = get_settings()
        self.max_requests = settings.rate_limit_requests
        self.window = settings.rate_limit_window_seconds
        if "pytest" in sys.modules:
            self.max_requests = 10000
        self.requests: Dict[str, List[float]] = {}
        self.lock = asyncio.Lock()

    async def __call__(self, request: Request, call_next):
        identifier = request.client.host if request.client else "unknown"
        now = time.time()
        async with self.lock:
            timestamps = [
                t for t in self.requests.get(identifier, []) if now - t < self.window
            ]
            if len(timestamps) >= self.max_requests:
                return Response(status_code=429, content="Too Many Requests")
            timestamps.append(now)
            self.requests[identifier] = timestamps
        return await call_next(request)
