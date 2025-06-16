import os
import uvicorn
import inspect

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware

try:
    from brotli_asgi import BrotliMiddleware  # type: ignore

    _brotli = True
except Exception:  # pragma: no cover - optional dep may not be installed
    BrotliMiddleware = None  # type: ignore
    _brotli = False
from app.initial_setup import create_initial_admin_user
from app.connectors import init_connectors
from app.api import init_routers
from app.app_routes import app_routes
from app.core.config import settings
from app.auth_middleware import auth_middleware
from app.core.logging import request_context_middleware
from app.core.rate_limit import (
    RateLimiter,
    MemoryRateLimitStore,
    RedisRateLimitStore,
)
from app.core.exception_handlers import add_exception_handlers


def run_alembic_migrations():
    if not os.path.exists("alembic/versions"):
        os.makedirs("alembic/versions", exist_ok=True)
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(alembic_cfg, "head")


app = FastAPI()

if settings.rate_limit_backend == "redis":
    store = RedisRateLimitStore(settings.rate_limit_redis_url)
else:
    store = MemoryRateLimitStore()

rate_limiter = RateLimiter(store=store)

if _brotli and BrotliMiddleware:
    app.add_middleware(BrotliMiddleware)
else:
    app.add_middleware(GZipMiddleware, minimum_size=500)

app.middleware("http")(request_context_middleware)
app.middleware("http")(rate_limiter)


@app.middleware("http")
async def cache_control_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.method == "GET" and response.headers.get("content-type", "").startswith(
        "application/json"
    ):
        response.headers.setdefault("Cache-Control", "max-age=60")
    return response


# Create the initial user
@app.on_event("startup")
async def startup_event():
    if not os.environ.get("SKIP_MIGRATIONS"):
        if not os.path.exists("db"):
            os.makedirs("db", exist_ok=True)
        run_alembic_migrations()
        create_initial_admin_user()


# add authentication
app.middleware("http")(auth_middleware)

# Initialize the connectors
init_connectors(app, settings)

# Initialize the routers
init_routers(app)
add_exception_handlers(app)

current_dir = os.path.dirname(os.path.realpath(__file__))
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(current_dir, "app/static")),
    name="static",
)


# Include app_routes
app.include_router(app_routes)


def main() -> None:
    """Run the FastAPI application using Uvicorn."""
    kwargs = {
        "host": settings.host,
        "port": settings.port,
        "reload": settings.debug,
        "log_level": settings.log_level.lower(),
    }
    if "compression" in inspect.signature(uvicorn.Config).parameters:
        kwargs["compression"] = "brotli" if _brotli else "gzip"
    uvicorn.run(app, **kwargs)


if __name__ == "__main__":
    main()

