import os
import uvicorn

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.initial_setup import create_initial_admin_user
from app.connectors import init_connectors
from app.api import init_routers
from app.app_routes import app_routes
from app.core.config import settings
from app.auth_middleware import auth_middleware

def run_alembic_migrations():
    if not os.path.exists("alembic/versions"):
        os.makedirs("alembic/versions", exist_ok=True)
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(alembic_cfg, "head")

app = FastAPI()

# Create the initial user
@app.on_event("startup")
async def startup_event():
    run_alembic_migrations()
    create_initial_admin_user()

# add authentication
app.middleware("http")(auth_middleware)

# Initialize the connectors
init_connectors(app, settings)

# Initialize the routers
init_routers(app)

current_dir = os.path.dirname(os.path.realpath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(current_dir, "app/static")), name="static")


# Include app_routes
app.include_router(app_routes)

if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port, debug=settings.debug)

