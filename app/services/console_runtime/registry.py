from __future__ import annotations

from app.services.console_runtime.kernel import ConsoleRuntimeKernel

_runtime_kernel = ConsoleRuntimeKernel()


def get_runtime_kernel() -> ConsoleRuntimeKernel:
    return _runtime_kernel


def reset_runtime_kernel() -> ConsoleRuntimeKernel:
    global _runtime_kernel
    _runtime_kernel = ConsoleRuntimeKernel()
    return _runtime_kernel
