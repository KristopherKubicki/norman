"""Scheduler tests for Kaizen's bounded, observe-only broker loop."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.kaizen.supervisor import KaizenBrokerService


class _Session:
    def close(self) -> None:
        return None


class _Store:
    def __init__(self, scopes: list[tuple[int, str, str]]) -> None:
        self.scopes = sorted(scopes)
        self.selection_calls: list[tuple[tuple[int, str, str] | None, int]] = []

    def list_fresh_pilot_snapshot_scopes(
        self,
        _db,
        *,
        after_scope: tuple[int, str, str] | None = None,
        limit: int,
        **_kwargs,
    ) -> list[tuple[int, str, str]]:
        self.selection_calls.append((after_scope, limit))
        selected = [
            scope for scope in self.scopes if after_scope is None or scope > after_scope
        ]
        return selected[:limit]


class _Broker:
    def __init__(
        self,
        *,
        failures: set[tuple[int, str, str]] | None = None,
        result: str = "observe_only",
    ) -> None:
        self.failures = failures or set()
        self.result = result
        self.scopes: list[tuple[int, str, str]] = []

    def tick(self, _db, *, user_id: int, realm: str, source_tui: str, **_kwargs):
        scope = (user_id, realm, source_tui)
        self.scopes.append(scope)
        if scope in self.failures:
            raise RuntimeError("broker test failure")
        return {
            "decision": {
                "result": self.result,
                "reason": "no_action_observe_only",
            }
        }


def _settings(*, enabled: bool = True, max_admissions: int = 2):
    return SimpleNamespace(
        kaizen_enabled=enabled,
        kaizen_observe_only=True,
        kaizen_auto_actions_enabled=False,
        kaizen_candidate_shadow_enabled=False,
        kaizen_pilot_tui_ids=["pilot-a", "pilot-b"],
        kaizen_allowed_realms=["personal/home"],
        kaizen_idle_grace_seconds=900,
        kaizen_snapshot_max_age_seconds=300,
        kaizen_candidate_evidence_max_age_seconds=300,
        kaizen_daily_norllama_token_budget=0,
        kaizen_candidate_shadow_max_tokens=0,
        kaizen_candidate_shadow_max_concurrency=0,
        kaizen_report_timezone="America/Chicago",
        kaizen_broker_tick_seconds=1,
        kaizen_max_admissions_per_tick=max_admissions,
    )


def _service(
    store: _Store,
    broker: _Broker,
    *,
    settings_obj=None,
) -> KaizenBrokerService:
    return KaizenBrokerService(
        store=store,
        broker=broker,
        settings_obj=settings_obj or _settings(),
        session_factory=_Session,
        clock=lambda: datetime(2026, 8, 2, 16, tzinfo=timezone.utc),
        environ={},
    )


@pytest.mark.asyncio
async def test_kaizen_supervisor_is_disabled_by_default() -> None:
    store = _Store([(1, "personal/home", "pilot-a")])
    broker = _Broker()
    service = _service(store, broker, settings_obj=_settings(enabled=False))

    admissions = await service._tick()
    snapshot = await service.snapshot()

    assert admissions == 0
    assert store.selection_calls == []
    assert broker.scopes == []
    assert snapshot.enabled is False
    assert snapshot.running is False


@pytest.mark.asyncio
async def test_kaizen_supervisor_bounds_each_tick_by_admission_capacity() -> None:
    scopes = [
        (1, "personal/home", "pilot-a"),
        (2, "personal/home", "pilot-a"),
        (3, "personal/home", "pilot-b"),
    ]
    store = _Store(scopes)
    broker = _Broker()
    service = _service(store, broker, settings_obj=_settings(max_admissions=2))

    admissions = await service._tick()
    snapshot = await service.snapshot()

    assert admissions == 2
    assert broker.scopes == scopes[:2]
    assert store.selection_calls == [(None, 2)]
    assert snapshot.scopes_evaluated == 2
    assert snapshot.admissions == 2


@pytest.mark.asyncio
async def test_kaizen_supervisor_wraps_its_cursor_fairly() -> None:
    scopes = [
        (1, "personal/home", "pilot-a"),
        (2, "personal/home", "pilot-a"),
        (3, "personal/home", "pilot-b"),
    ]
    store = _Store(scopes)
    broker = _Broker()
    service = _service(store, broker, settings_obj=_settings(max_admissions=2))

    await service._tick()
    await service._tick()

    assert broker.scopes == [scopes[0], scopes[1], scopes[2], scopes[0]]
    assert store.selection_calls == [
        (None, 2),
        (scopes[1], 2),
        (None, 1),
    ]


@pytest.mark.asyncio
async def test_kaizen_supervisor_isolates_scope_failures() -> None:
    failed = (1, "personal/home", "pilot-a")
    succeeded = (2, "personal/home", "pilot-b")
    store = _Store([failed, succeeded])
    broker = _Broker(failures={failed})
    service = _service(store, broker)

    admissions = await service._tick()
    snapshot = await service.snapshot()

    assert admissions == 1
    assert broker.scopes == [failed, succeeded]
    assert snapshot.scopes_evaluated == 2
    assert snapshot.admissions == 1
    assert snapshot.failures == 1
    assert snapshot.last_result == {
        "realm": "personal/home",
        "source_tui": "pilot-b",
        "result": "observe_only",
        "reason": "no_action_observe_only",
    }


@pytest.mark.asyncio
async def test_kaizen_supervisor_start_and_stop_manage_the_background_task() -> None:
    store = _Store([])
    broker = _Broker()
    service = _service(store, broker)

    await service.start()
    await asyncio.sleep(0)
    running = await service.snapshot()
    await service.stop()
    stopped = await service.snapshot()

    assert running.enabled is True
    assert running.running is True
    assert stopped.running is False
