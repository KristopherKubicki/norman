from fastapi import APIRouter, FastAPI
from .api_v1.routers import (
    actions_router,
    bots_router,
    channels_router,
    filters_router,
    connectors_router,
)

router = APIRouter()

router.include_router(actions_router, prefix="/v1/actions")
router.include_router(bots_router, prefix="/v1/bots")
router.include_router(channels_router, prefix="/v1/channels")
router.include_router(filters_router, prefix="/v1/filters")
router.include_router(connectors_router, prefix="/v1/connectors")

def init_routers(app: FastAPI):
    app.include_router(router, prefix="/api")
