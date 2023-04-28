from typing import List
from fastapi import FastAPI
from .actions import router as actions_router
from .bots import router as bots_router
from .channels import router as channels_router
from .filters import router as filters_router
from .connectors import router as connectors_router

ROUTER_MODULES = [
    ("actions", actions_router),
    ("bots", bots_router),
    ("channels", channels_router),
    ("filters", filters_router),
    ("connectors", connectors_router),
]

def init_routers(app: FastAPI, routers: List[str]):
    for route_prefix, router in ROUTER_MODULES:
        if route_prefix in routers:
            app.include_router(router, prefix=f"/api/{route_prefix}")

