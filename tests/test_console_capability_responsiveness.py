"""Slow mesh discovery must not freeze unrelated HTTP requests."""

import asyncio
import threading
from types import SimpleNamespace

from app.api.api_v1.routers import console_runtime


def test_capability_probe_leaves_the_event_loop_responsive(monkeypatch):
    """A loop callback can release a blocked discovery probe before its timeout."""
    released = threading.Event()
    monkeypatch.setattr(console_runtime, "_read_cache_enabled", lambda: False)
    monkeypatch.setattr(console_runtime, "_kernel_capability_payload", lambda: {})
    monkeypatch.setattr(
        console_runtime,
        "_norllama_capability_snapshot",
        lambda: {"loop_remained_responsive": released.wait(timeout=1)},
    )

    async def exercise():
        asyncio.get_running_loop().call_later(0.05, released.set)
        return await console_runtime.get_console_runtime_capabilities(
            current_user=SimpleNamespace(id=987654321),
        )

    result = asyncio.run(exercise())
    assert result["norllama"]["loop_remained_responsive"] is True
