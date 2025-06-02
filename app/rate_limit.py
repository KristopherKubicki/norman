from time import time
from fastapi import Request
from fastapi.responses import PlainTextResponse

RATE_LIMIT = 10
WINDOW = 60
_attempts = {}


async def rate_limit_middleware(request: Request, call_next):
    if request.url.path == "/login" and request.method.lower() == "post":
        ip = request.client.host if request.client else "unknown"
        now = time()
        attempts = _attempts.get(ip, [])
        attempts = [t for t in attempts if now - t < WINDOW]
        if len(attempts) >= RATE_LIMIT:
            return PlainTextResponse("Too Many Requests", status_code=429)
        attempts.append(now)
        _attempts[ip] = attempts
    return await call_next(request)
