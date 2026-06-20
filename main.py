import os
import asyncio
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
from app.db import session as db_session
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
from app.services.connector_health import connector_health
from app.services.console_audit_monitor import console_audit_monitor
from app.services.fleet_credit_monitor import fleet_credit_monitor
from app.services.estate_sync import sync_registry
from app.services.passive_udp_listeners import passive_udp_listeners
from app.services.tmux_reconciler import reconcile_tmux_connectors_for_startup
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
            stdin=subprocess.DEVNULL,
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
    # NOTE: We intentionally do *not* override SIGINT/SIGTERM. Uvicorn installs
    # its own handlers for graceful shutdown.
    #
    # Screen/tmux can send SIGHUP when a session/window closes; forward that to
    # SIGTERM so Uvicorn can run shutdown events and release the port cleanly.
    logger.error("Received signal %s; forwarding to SIGTERM", signum)
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except Exception:
        raise SystemExit(0)


for _sig in (signal.SIGHUP, signal.SIGQUIT):
    try:
        signal.signal(_sig, _handle_signal)
    except Exception:
        pass


@atexit.register
def _on_exit():
    # Avoid logging during interpreter shutdown. Some environments (pytest's
    # output capture) close streams first, and the logging module prints noisy
    # "Logging error" diagnostics even when exceptions are suppressed.
    return


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
    path = request.url.path
    if request.method == "GET":
        if path.startswith("/static/icons/"):
            response.headers.setdefault(
                "Cache-Control", "public, max-age=86400, immutable"
            )
        elif path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "public, max-age=3600")
        elif response.headers.get("content-type", "").startswith("application/json"):
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
            Base.metadata.create_all(bind=db_session.engine)
        except Exception:
            logger.exception("Startup: failed creating tables")
            raise
        if not os.environ.get("SKIP_ESTATE_SEED"):
            logger.info("Startup: syncing estate registry seed")
            estate_db = db_session.SessionLocal()
            try:
                summary = sync_registry(estate_db)
                logger.info("Startup: estate registry sync summary %s", summary)
            except Exception:
                logger.exception("Startup: estate registry sync failed")
            finally:
                estate_db.close()
        logger.info("Startup: migrations complete")

        # Ensure there is at least one admin user on first boot.
        try:
            create_initial_admin_user()
        except Exception:
            logger.exception("Startup: failed creating initial admin user")
            raise
        if not os.environ.get("SKIP_TMUX_RECONCILE"):
            logger.info("Startup: reconciling tmux project sessions")
            try:
                summary = await asyncio.to_thread(reconcile_tmux_connectors_for_startup)
                logger.info(f"Startup: tmux reconcile summary {summary}")
            except Exception:
                # Keep the app available even if tmux automation fails.
                logger.exception("Startup: tmux reconcile failed")

        if not os.environ.get("SKIP_CONNECTOR_HEALTH"):
            logger.info("Startup: starting connector health scheduler")
            await connector_health.start()
            app.state.connector_health_enabled = True
        if not os.environ.get("SKIP_FLEET_CREDIT_MONITOR"):
            logger.info("Startup: starting fleet credit monitor")
            await fleet_credit_monitor.start()
            app.state.fleet_credit_monitor_enabled = True
        if not os.environ.get("SKIP_CONSOLE_AUDIT_MONITOR"):
            logger.info("Startup: starting console audit monitor")
            await console_audit_monitor.start()
            app.state.console_audit_monitor_enabled = True
        try:
            await passive_udp_listeners.start()
            app.state.passive_udp_listeners_enabled = True
        except Exception:
            logger.exception("Startup: failed starting passive UDP listeners")
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
    if getattr(app.state, "connector_health_enabled", False):
        await connector_health.stop()
    if getattr(app.state, "fleet_credit_monitor_enabled", False):
        await fleet_credit_monitor.stop()
    if getattr(app.state, "console_audit_monitor_enabled", False):
        await console_audit_monitor.stop()
    if getattr(app.state, "passive_udp_listeners_enabled", False):
        await passive_udp_listeners.stop()
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
