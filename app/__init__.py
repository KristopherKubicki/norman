"""Application package initialization."""

from typing import ForwardRef, Any, cast
import inspect
import sys
import pydantic.typing as _pydantic_typing

# Pydantic 1.x doesn't support Python 3.12's updated ForwardRef._evaluate
sig = inspect.signature(ForwardRef._evaluate)
py_ver = sys.version_info
if py_ver >= (3, 12) and 'recursive_guard' in sig.parameters:
    def _evaluate_forwardref(type_: ForwardRef, globalns: Any, localns: Any) -> Any:
        return cast(Any, type_)._evaluate(globalns, localns, None, recursive_guard=set())

    _pydantic_typing.evaluate_forwardref = _evaluate_forwardref
elif py_ver < (3, 12) and 'recursive_guard' not in sig.parameters:
    def _evaluate_forwardref(type_: ForwardRef, globalns: Any, localns: Any) -> Any:
        return cast(Any, type_)._evaluate(globalns, localns, None)

    _pydantic_typing.evaluate_forwardref = _evaluate_forwardref

