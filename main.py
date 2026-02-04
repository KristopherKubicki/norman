import os
import uvicorn
import inspect as uvicorn_inspect
import signal
import atexit
import faulthandler
import subprocess
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from app.db.session import engine
from app.db.base import Base
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
from app.core.rate_limit import RateLimiter
from app.core.exception_handlers import add_exception_handlers
from app.routing.worker import start_routing_worker
from app.core.logging import setup_logger


def run_alembic_migrations():
    if not os.path.exists("alembic/versions"):
        os.makedirs("alembic/versions", exist_ok=True)
    logger.info("Alembic: upgrade head start")
    try:
        # Run alembic in a subprocess to avoid abrupt exits in the main process.
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
            capture_output=True,
            text=True,
        )
        if result.stdout:
            logger.info("Alembic stdout: %s", result.stdout.strip())
        if result.stderr:
            logger.warning("Alembic stderr: %s", result.stderr.strip())
    except subprocess.CalledProcessError as exc:
        logger.error("Alembic failed: %s", exc.stderr or exc.stdout or str(exc))
        raise
    logger.info("Alembic: upgrade head done")


app = FastAPI()
logger = setup_logger(__name__)
faulthandler.enable()


def _handle_signal(signum, _frame):
    logger.error("Received signal %s; exiting", signum)


for _sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT):
    try:
        signal.signal(_sig, _handle_signal)
    except Exception:
        pass


@atexit.register
def _on_exit():
    logger.error("Process exiting")


rate_limiter = RateLimiter()

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
    logger.info("Startup: begin")
    try:
        should_skip = os.environ.get("SKIP_MIGRATIONS")
        if not should_skip:
            if not os.path.exists("db"):
                os.makedirs("db", exist_ok=True)
            logger.info("Startup: running migrations")
            run_alembic_migrations()
        logger.info("Startup: ensuring tables exist")
        try:
            Base.metadata.create_all(bind=engine)
        except Exception:
            logger.exception("Startup: failed creating tables")
            raise
        logger.info("Startup: migrations complete")
        return

        try:
            inspector = inspect(engine)
            has_users = inspector.has_table("users")
        except Exception:
            has_users = False

        if not has_users:
            if not os.path.exists("db"):
                os.makedirs("db", exist_ok=True)
            logger.info("Startup: users table missing; running migrations")
            run_alembic_migrations()
        logger.info("Startup: ensuring tables exist after migrations")
        try:
            Base.metadata.create_all(bind=engine)
        except Exception:
            logger.exception("Startup: failed creating tables")
            raise
        logger.info("Startup: migrations skipped")
        if not os.environ.get("SKIP_ROUTING_WORKER"):
            logger.info("Startup: starting routing worker")
            task, stop_event = start_routing_worker()
            app.state.routing_task = task
            app.state.routing_stop_event = stop_event
        logger.info("Startup: complete")
    except BaseException:
        logger.exception("Startup: failed")
        raise


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutdown: begin")
    stop_event = getattr(app.state, "routing_stop_event", None)
    task = getattr(app.state, "routing_task", None)
    if stop_event:
        stop_event.set()
    if task:
        task.cancel()
    logger.info("Shutdown: complete")


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
    if "compression" in uvicorn_inspect.signature(uvicorn.Config).parameters:
        kwargs["compression"] = "brotli" if _brotli else "gzip"
    uvicorn.run(app, **kwargs)


if __name__ == "__main__":
    main()
