"""Dashboard database and host probes must not stall the web event loop."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from app.api.api_v1.routers import console_runtime as router


@pytest.mark.parametrize("endpoint", ["jobs", "route-summary", "worker-status"])
def test_dashboard_reads_leave_event_loop_responsive(monkeypatch, endpoint):
    """An independent callback runs while a dashboard loader is still blocked."""
    entered = threading.Event()
    release = threading.Event()

    def slow_read(*args, **kwargs):
        entered.set()
        assert release.wait(2), "dashboard loader blocked the event loop"
        return {}

    monkeypatch.setattr(router, "_cached_read", slow_read)
    monkeypatch.setattr(router, "_read_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(router, "_worker_status_payload", slow_read)
    monkeypatch.setattr(router, "_norllama_runtime_status_snapshot", lambda **k: {})

    async def status_payload(**kwargs):
        return {}

    monkeypatch.setattr(
        router.console_runtime_worker_service, "status_payload", status_payload
    )

    async def exercise():
        user = SimpleNamespace(id=-987654)
        if endpoint == "jobs":
            call = router.list_console_runtime_jobs(
                limit=200, current_user=user, db=None
            )
        elif endpoint == "route-summary":
            call = router.get_console_runtime_route_summary(
                job_id="", limit=1000, current_user=user, db=None
            )
        else:
            call = router.get_console_runtime_worker_status(current_user=user, db=None)
        task = asyncio.create_task(call)
        try:
            for _ in range(100):
                await asyncio.sleep(0.01)
                if entered.is_set():
                    break
            assert entered.is_set()
            assert not task.done()
        finally:
            release.set()
        await task

    asyncio.run(exercise())
