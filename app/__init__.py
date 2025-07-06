"""Application package initialization."""

from typing import ForwardRef, Any, cast
import inspect
import pydantic.typing as _pydantic_typing

# Pydantic 1.x doesn't fully support Python's various ForwardRef._evaluate
# signatures across versions. We inspect the signature and delegate accordingly
# so that both Python <3.12 and >=3.12 work.
sig = inspect.signature(ForwardRef._evaluate)
if "recursive_guard" in sig.parameters:

    def _evaluate_forwardref(type_: ForwardRef, globalns: Any, localns: Any) -> Any:
        if "type_params" in sig.parameters:
            # Python >=3.12 has a ``type_params`` positional argument and
            # ``recursive_guard`` is keyword only
            return cast(Any, type_)._evaluate(
                globalns, localns, None, recursive_guard=set()
            )
        else:
            # Older versions expect ``recursive_guard`` as the third positional
            return cast(Any, type_)._evaluate(globalns, localns, recursive_guard=set())

    _pydantic_typing.evaluate_forwardref = _evaluate_forwardref
