# main.py

from fastapi import FastAPI
from app.api.api_v1.api import api_router
from app.core.config import settings

from connectors import init_connectors
from api import init_routers

app = FastAPI(title=settings.PROJECT_NAME)

app.include_router(api_router, prefix="/api/api_v1")

if __name__ == "__main__":
    import uvicorn
 
    # initialize the connectors first
    connectors_config = settings.connectors
    init_connectors(app, connectors_config)

    # setup all routes
    routers_to_include = ["actions", "bots", "channels", "filters", "connectors"]
    init_routers(app, routers_to_include)

    uvicorn.run(app, host="0.0.0.0", port=8000)
