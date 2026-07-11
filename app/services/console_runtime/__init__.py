"""Provider-neutral console runtime primitives for Norman."""

from app.services.console_runtime.adapters.base import ModelAdapter
from app.services.console_runtime.kernel import (
    ConsoleRuntimeError,
    ConsoleRuntimeKernel,
    InvalidTransitionError,
    JobNotFoundError,
)
from app.services.console_runtime.registry import get_runtime_kernel
from app.services.console_runtime.store import (
    DbConsoleRuntimeStore,
    db_console_runtime_store,
)
from app.services.console_runtime.supervisor import (
    ConsoleRuntimeWorkerService,
    ConsoleRuntimeWorkerSnapshot,
    console_runtime_worker_service,
)
from app.services.console_runtime.types import (
    ConsoleJob,
    ConsoleJobContract,
    ConsoleJobLease,
    ConsoleJobStatus,
    ModelBudget,
    ModelCapabilities,
    ModelRequest,
    ModelResult,
    ModelUsage,
    RouteDecision,
    RuntimeModeState,
)
from app.services.console_runtime.worker import (
    ConsoleRuntimeRunOptions,
    DbConsoleRuntimeWorker,
)

__all__ = [
    "ConsoleJob",
    "ConsoleJobContract",
    "ConsoleJobLease",
    "ConsoleJobStatus",
    "ConsoleRuntimeError",
    "ConsoleRuntimeRunOptions",
    "ConsoleRuntimeKernel",
    "ConsoleRuntimeWorkerService",
    "ConsoleRuntimeWorkerSnapshot",
    "console_runtime_worker_service",
    "DbConsoleRuntimeStore",
    "DbConsoleRuntimeWorker",
    "db_console_runtime_store",
    "get_runtime_kernel",
    "InvalidTransitionError",
    "JobNotFoundError",
    "ModelAdapter",
    "ModelBudget",
    "ModelCapabilities",
    "ModelRequest",
    "ModelResult",
    "ModelUsage",
    "RouteDecision",
    "RuntimeModeState",
]
