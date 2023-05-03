import os
import uvicorn

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.connectors import init_connectors
from app.api import init_routers
from app.app_routes import app_routes
from app.core.config import settings
from app.auth_middleware import auth_middleware

app = FastAPI()

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

