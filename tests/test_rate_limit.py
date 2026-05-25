import asyncio
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response
from main import rate_limiter


def test_rate_limiting(test_app: TestClient) -> None:
    rate_limiter.requests.clear()
    rate_limiter.max_requests = 2

    async def call_next(_: Request) -> Response:
        return Response("ok", status_code=200)

    def make_request() -> Request:
        scope = {
            "type": "http",
            "client": ("127.0.0.1", 123),
            "headers": [],
            "path": "/api/connectors/create",
            "query_string": b"",
            "method": "POST",
            "scheme": "http",
            "server": ("testserver", 80),
        }
        return Request(scope)

    for _ in range(2):
        resp = asyncio.run(rate_limiter(make_request(), call_next))
        assert resp.status_code == 200

    resp = asyncio.run(rate_limiter(make_request(), call_next))
    assert resp.status_code == 429

    rate_limiter.max_requests = 10000
    rate_limiter.requests.clear()


def test_rate_limiter_skips_read_requests() -> None:
    rate_limiter.requests.clear()
    rate_limiter.max_requests = 1

    async def call_next(_: Request) -> Response:
        return Response("ok", status_code=200)

    def make_request(path: str, method: str = "GET") -> Request:
        scope = {
            "type": "http",
            "client": ("127.0.0.1", 123),
            "headers": [],
            "path": path,
            "query_string": b"",
            "method": method,
            "scheme": "http",
            "server": ("testserver", 80),
        }
        return Request(scope)

    for path in (
        "/connectors.html",
        "/api/connectors",
        "/api/v1/connectors/available",
        "/static/icons/connectors/slack.svg",
    ):
        resp = asyncio.run(rate_limiter(make_request(path, "GET"), call_next))
        assert resp.status_code == 200

    rate_limiter.max_requests = 10000
    rate_limiter.requests.clear()
