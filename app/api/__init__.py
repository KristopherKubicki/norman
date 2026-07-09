from fastapi import APIRouter, FastAPI
from .api_v1.routers import (
    actions_router,
    bots_router,
    channels_router,
    filters_router,
    connectors_router,
    platform_connectors_router,
    tmux_router,
    console_targets_router,
    users_router,
    routing_router,
    approvals_router,
    estate_router,
    keys_router,
    operator_state_router,
    console_runtime_router,
)
from app.core.config import get_settings

settings = get_settings()

router = APIRouter()

api_prefix = f"/{settings.api_version}"

router.include_router(actions_router, prefix=api_prefix)
router.include_router(bots_router, prefix=f"{api_prefix}/bots")
router.include_router(channels_router, prefix=f"{api_prefix}/channels")
router.include_router(filters_router, prefix=api_prefix)
router.include_router(connectors_router, prefix=api_prefix)
router.include_router(platform_connectors_router, prefix=f"{api_prefix}/connectors")
router.include_router(tmux_router, prefix=api_prefix)
router.include_router(console_targets_router, prefix=api_prefix)
router.include_router(users_router, prefix=f"{api_prefix}/users")
router.include_router(routing_router, prefix=api_prefix)
router.include_router(approvals_router, prefix=api_prefix)
router.include_router(estate_router, prefix=api_prefix)
router.include_router(keys_router, prefix=api_prefix)
router.include_router(operator_state_router, prefix=api_prefix)
router.include_router(console_runtime_router, prefix=api_prefix)


def init_routers(app: FastAPI):
    app.include_router(router, prefix=settings.api_prefix)
