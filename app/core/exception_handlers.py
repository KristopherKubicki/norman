from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .exceptions import (
    APIError,
    AuthenticationError,
    AuthorizationError,
    DatabaseError,
    NormanError,
)
from .logging import setup_logger

logger = setup_logger(__name__)


def add_exception_handlers(app: FastAPI) -> None:
    """Register standard exception handlers on the given ``app``."""

    async def _handle(request: Request, exc: Exception, status: int, detail: str):
        logger.error("%s on %s: %s", exc.__class__.__name__, request.url.path, exc)
        return JSONResponse(status_code=status, content={"detail": detail})

    @app.exception_handler(AuthenticationError)
    async def _auth_exc_handler(request: Request, exc: AuthenticationError):
        return await _handle(request, exc, 401, str(exc))

    @app.exception_handler(AuthorizationError)
    async def _authz_exc_handler(request: Request, exc: AuthorizationError):
        return await _handle(request, exc, 403, str(exc))

    @app.exception_handler(DatabaseError)
    async def _db_exc_handler(request: Request, exc: DatabaseError):
        return await _handle(request, exc, 500, "Database error")

    @app.exception_handler(APIError)
    async def _api_exc_handler(request: Request, exc: APIError):
        return await _handle(request, exc, 502, str(exc))

    @app.exception_handler(NormanError)
    async def _norman_exc_handler(request: Request, exc: NormanError):
        return await _handle(request, exc, 500, str(exc))
