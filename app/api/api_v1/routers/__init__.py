from .approvals import router as approvals_router
from .actions import router as actions_router
from .bots import router as bots_router
from .channels import router as channels_router
from .filters import router as filters_router
from .connectors_crud import router as connectors_router
from .connectors import router as platform_connectors_router
from .tmux import router as tmux_router
from .console_targets import router as console_targets_router
from .user import router as users_router
from .routing import router as routing_router
from .estate import router as estate_router
from .keys import compat_router as keys_compat_router
from .keys import router as keys_router
from .operator_state import router as operator_state_router
from .console_runtime import router as console_runtime_router

__all__ = [
    "actions_router",
    "bots_router",
    "channels_router",
    "filters_router",
    "connectors_router",
    "platform_connectors_router",
    "tmux_router",
    "console_targets_router",
    "users_router",
    "routing_router",
    "approvals_router",
    "estate_router",
    "keys_router",
    "keys_compat_router",
    "operator_state_router",
    "console_runtime_router",
]
