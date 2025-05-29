"""Application package initialization."""

from typing import ForwardRef, Any, cast
import inspect
import pydantic.typing as _pydantic_typing

# Pydantic 1.x doesn't support Python 3.12's updated ForwardRef._evaluate
sig = inspect.signature(ForwardRef._evaluate)
if 'recursive_guard' in sig.parameters:
    def _evaluate_forwardref(type_: ForwardRef, globalns: Any, localns: Any) -> Any:
        return cast(Any, type_)._evaluate(globalns, localns, None, recursive_guard=set())

    _pydantic_typing.evaluate_forwardref = _evaluate_forwardref

