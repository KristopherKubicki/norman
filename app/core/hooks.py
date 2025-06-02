import asyncio
from typing import Awaitable, Callable, List, Tuple, Union

# Type alias for hook callables
PreHook = Callable[[str, dict], Union[Awaitable[Tuple[str, dict]], Tuple[str, dict]]]
PostHook = Callable[[str, dict], Union[Awaitable[Tuple[str, dict]], Tuple[str, dict]]]

_pre_hooks: List[PreHook] = []
_post_hooks: List[PostHook] = []


def register_pre_hook(hook: PreHook) -> None:
    """Register a function to run before sending a message to the AI."""
    _pre_hooks.append(hook)


def register_post_hook(hook: PostHook) -> None:
    """Register a function to run after receiving a reply from the AI."""
    _post_hooks.append(hook)


async def run_pre_hooks(message: str, context: dict) -> Tuple[str, dict]:
    """Execute all registered pre-processing hooks."""
    for hook in _pre_hooks:
        result = hook(message, context)
        if asyncio.iscoroutine(result):
            message, context = await result
        else:
            message, context = result
    return message, context


async def run_post_hooks(reply: str, context: dict) -> Tuple[str, dict]:
    """Execute all registered post-processing hooks."""
    for hook in _post_hooks:
        result = hook(reply, context)
        if asyncio.iscoroutine(result):
            reply, context = await result
        else:
            reply, context = result
    return reply, context
