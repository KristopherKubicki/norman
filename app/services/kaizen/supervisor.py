"""Bounded background scheduling for the observe-only Kaizen broker."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Optional

from app.core.config import settings
from app.core.logging import setup_logger
from app.db import session as db_session
from app.services.kaizen.broker import KaizenBroker, kaizen_broker
from app.services.kaizen.store import DbKaizenStore, db_kaizen_store
from app.services.kaizen.types import KaizenConfig, as_utc, utc_now

logger = setup_logger(__name__)

Scope = tuple[int, str, str]


@dataclass
class KaizenBrokerSnapshot:
    enabled: bool
    running: bool
    tick_count: int = 0
    scopes_evaluated: int = 0
    admissions: int = 0
    skips: int = 0
    failures: int = 0
    last_result: dict[str, str] | None = None


class KaizenBrokerService:
    """Fairly evaluate fresh pilot snapshots without creating runtime work."""

    def __init__(
        self,
        *,
        store: DbKaizenStore | None = None,
        broker: KaizenBroker | None = None,
        settings_obj: Any | None = None,
        session_factory: Callable[[], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._store = store or db_kaizen_store
        self._broker = broker or kaizen_broker
        self._settings = settings_obj if settings_obj is not None else settings
        self._session_factory = session_factory or db_session.SessionLocal
        self._clock = clock or utc_now
        self._environ = environ if environ is not None else os.environ
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._lock = asyncio.Lock()
        self._cursor: Scope | None = None
        self._snapshot = KaizenBrokerSnapshot(
            enabled=self._is_enabled(),
            running=False,
        )

    async def start(self) -> None:
        """Start polling only when the explicit scheduler switch is enabled."""
        if not self._is_enabled():
            await self._set_disabled()
            return
        if self._task and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="kaizen_broker")

    async def stop(self) -> None:
        """Stop the in-process poller and retain its aggregate counters."""
        if self._stop_event:
            self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._stop_event = None
        async with self._lock:
            self._snapshot.running = False
            self._snapshot.enabled = self._is_enabled()

    async def snapshot(self) -> KaizenBrokerSnapshot:
        """Return an isolated view of the scheduler's aggregate state."""
        async with self._lock:
            last_result = (
                dict(self._snapshot.last_result)
                if self._snapshot.last_result is not None
                else None
            )
            return KaizenBrokerSnapshot(
                enabled=self._snapshot.enabled,
                running=self._snapshot.running,
                tick_count=self._snapshot.tick_count,
                scopes_evaluated=self._snapshot.scopes_evaluated,
                admissions=self._snapshot.admissions,
                skips=self._snapshot.skips,
                failures=self._snapshot.failures,
                last_result=last_result,
            )

    async def _run_loop(self) -> None:
        assert self._stop_event is not None
        async with self._lock:
            self._snapshot.enabled = True
            self._snapshot.running = True
        logger.info("KaizenBrokerService: started")
        try:
            while not self._stop_event.is_set():
                if not self._is_enabled():
                    await self._set_disabled()
                    break
                await self._tick()
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._tick_seconds(),
                    )
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("KaizenBrokerService: loop crashed")
        finally:
            async with self._lock:
                self._snapshot.enabled = self._is_enabled()
                self._snapshot.running = False
            logger.info("KaizenBrokerService: stopped")

    async def _tick(self) -> int:
        """Evaluate a bounded fair batch and return the observe-only admissions."""
        if not self._is_enabled():
            await self._set_disabled()
            return 0

        config = KaizenConfig.from_settings(self._settings)
        capacity = self._max_admissions_per_tick()
        now = as_utc(self._clock())
        scopes: list[Scope] = []
        selection_failed = False
        if capacity:
            try:
                scopes = await asyncio.to_thread(
                    self._select_scopes,
                    config,
                    now,
                    capacity,
                )
            except Exception:
                selection_failed = True
                logger.exception("KaizenBrokerService: scope selection failed")

        admissions = 0
        skips = 0
        failures = 1 if selection_failed else 0
        last_result: dict[str, str] | None = (
            {"failure": "scope_selection_failed"} if selection_failed else None
        )
        for scope in scopes:
            self._cursor = scope
            user_id, realm, source_tui = scope
            try:
                outcome = await asyncio.to_thread(
                    self._tick_scope,
                    user_id,
                    realm,
                    source_tui,
                    config,
                    now,
                )
                decision = outcome.get("decision")
                result = (
                    str(decision.get("result") or "")
                    if isinstance(decision, dict)
                    else ""
                )
                reason = (
                    str(decision.get("reason") or "")
                    if isinstance(decision, dict)
                    else ""
                )
                if result == "observe_only":
                    admissions += 1
                else:
                    skips += 1
                last_result = {
                    "realm": realm,
                    "source_tui": source_tui,
                    "result": result or "invalid_result",
                    "reason": reason or "missing_reason",
                }
            except Exception as exc:
                failures += 1
                last_result = {
                    "realm": realm,
                    "source_tui": source_tui,
                    "failure": type(exc).__name__,
                }
                logger.exception(
                    "KaizenBrokerService: scope evaluation failed",
                    extra={
                        "user_id": user_id,
                        "realm": realm,
                        "source_tui": source_tui,
                    },
                )

        async with self._lock:
            self._snapshot.enabled = True
            self._snapshot.running = True
            self._snapshot.tick_count += 1
            self._snapshot.scopes_evaluated += len(scopes)
            self._snapshot.admissions += admissions
            self._snapshot.skips += skips
            self._snapshot.failures += failures
            self._snapshot.last_result = last_result
        return admissions

    def _select_scopes(
        self,
        config: KaizenConfig,
        now: datetime,
        capacity: int,
    ) -> list[Scope]:
        """Select after the fair cursor, then wrap once through the pilot set."""
        if capacity <= 0:
            return []
        observed_after = now - timedelta(seconds=config.snapshot_max_age_seconds)
        db = self._session_factory()
        try:
            scopes = self._store.list_fresh_pilot_snapshot_scopes(
                db,
                pilot_tui_ids=config.pilot_tui_ids,
                allowed_realms=config.allowed_realms,
                observed_after=observed_after,
                observed_before=now,
                after_scope=self._cursor,
                limit=capacity,
            )
            if len(scopes) < capacity and self._cursor is not None:
                scopes.extend(
                    self._store.list_fresh_pilot_snapshot_scopes(
                        db,
                        pilot_tui_ids=config.pilot_tui_ids,
                        allowed_realms=config.allowed_realms,
                        observed_after=observed_after,
                        observed_before=now,
                        limit=capacity - len(scopes),
                    )
                )
            return scopes
        finally:
            db.close()

    def _tick_scope(
        self,
        user_id: int,
        realm: str,
        source_tui: str,
        config: KaizenConfig,
        now: datetime,
    ) -> dict[str, Any]:
        db = self._session_factory()
        try:
            return self._broker.tick(
                db,
                user_id=user_id,
                realm=realm,
                source_tui=source_tui,
                config=config,
                now=now,
            )
        finally:
            db.close()

    def _is_enabled(self) -> bool:
        return bool(getattr(self._settings, "kaizen_enabled", False)) and not bool(
            self._environ.get("SKIP_KAIZEN_BROKER")
        )

    def _max_admissions_per_tick(self) -> int:
        try:
            value = int(
                getattr(self._settings, "kaizen_max_admissions_per_tick", 1) or 0
            )
        except (TypeError, ValueError):
            return 0
        return max(0, min(value, 1000))

    def _tick_seconds(self) -> float:
        try:
            value = float(
                getattr(self._settings, "kaizen_broker_tick_seconds", 60) or 60
            )
        except (TypeError, ValueError):
            return 60.0
        return max(1.0, min(value, 3600.0))

    async def _set_disabled(self) -> None:
        async with self._lock:
            self._snapshot.enabled = False
            self._snapshot.running = False


kaizen_broker_service = KaizenBrokerService()
