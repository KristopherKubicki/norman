"""Model adapter implementations for the console runtime."""

from app.services.console_runtime.adapters.base import ModelAdapter
from app.services.console_runtime.adapters.fake import FakeModelAdapter
from app.services.console_runtime.adapters.norllama import NorllamaModelAdapter
from app.services.console_runtime.adapters.shell import (
    ShellPolicyError,
    ShellRequest,
    ShellResult,
    ShellRuntimeAdapter,
)

__all__ = [
    "FakeModelAdapter",
    "ModelAdapter",
    "NorllamaModelAdapter",
    "ShellPolicyError",
    "ShellRequest",
    "ShellResult",
    "ShellRuntimeAdapter",
]
