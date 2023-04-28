import uvicorn

from fastapi import FastAPI
from app.connectors import init_connectors
from app.api import init_routers
from app.app_routes import app_routes
from app.core.config import settings

app = FastAPI()

# Initialize the connectors
init_connectors(app, settings)



# Initialize the routers
init_routers(app)

app.include_router(app_routes)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

