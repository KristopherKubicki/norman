from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional

from app.connectors.connector_utils import get_connector
from app.core.logging import setup_logger
from app.db.session import SessionLocal
from app import models

logger = setup_logger(__name__)


@dataclass
class ConnectorHealthSnapshot:
    connector_id: int
    connector_type: str
    status: str  # up|down|missing_config|unknown
    checked_at: float
    next_check_at: float
    failures: int = 0
    error: str = ""


@dataclass
class ConnectorHealthHistoryEntry:
    connector_id: int
    connector_type: str
    status: str
    checked_at: float
    failures: int = 0
    error: str = ""


class ConnectorHealthService:
    """Background connector health checker with per-connector backoff.

    In-memory state is enough to stabilize the UI and reduce request volume.
    Persisted history can be added later.
    """

    def __init__(self) -> None:
        self._snapshots: Dict[int, ConnectorHealthSnapshot] = {}
        self._history: Dict[int, Deque[ConnectorHealthHistoryEntry]] = {}
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None

        # Tuning knobs.
        self.base_interval_s = 60.0
        self.min_interval_s = 15.0
        self.max_interval_s = 10 * 60.0
        self.tick_s = 2.0
        self.max_checks_per_tick = 12
        self.history_limit = 25

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="connector_health")

    async def stop(self) -> None:
        if not self._stop_event:
            return
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._stop_event = None

    async def kick(self, connector_id: int) -> None:
        """Force the connector to be eligible for an immediate refresh."""
        async with self._lock:
            snap = self._snapshots.get(connector_id)
            if snap:
                snap.next_check_at = 0.0

    async def kick_all(self, connector_ids: Optional[list[int]] = None) -> None:
        async with self._lock:
            if connector_ids is None:
                for snap in self._snapshots.values():
                    snap.next_check_at = 0.0
                return
            for connector_id in connector_ids:
                snap = self._snapshots.get(connector_id)
                if snap:
                    snap.next_check_at = 0.0

    async def get_snapshot(
        self, connector_id: int
    ) -> Optional[ConnectorHealthSnapshot]:
        async with self._lock:
            snap = self._snapshots.get(connector_id)
            if not snap:
                return None
            return ConnectorHealthSnapshot(**snap.__dict__)

    async def get_history(
        self, connector_id: int, *, limit: Optional[int] = None
    ) -> list[ConnectorHealthHistoryEntry]:
        async with self._lock:
            entries = self._history.get(connector_id)
            if not entries:
                return []
            items = list(entries)
        if limit is not None:
            items = items[-max(0, limit) :]
        items.reverse()
        return [ConnectorHealthHistoryEntry(**entry.__dict__) for entry in items]

    async def _run_loop(self) -> None:
        assert self._stop_event is not None
        logger.info("ConnectorHealth: started")
        try:
            while not self._stop_event.is_set():
                await self._tick()
                await asyncio.sleep(self.tick_s)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ConnectorHealth: loop crashed")
        finally:
            logger.info("ConnectorHealth: stopped")

    async def _tick(self) -> None:
        now = time.time()
        try:
            db = SessionLocal()
            try:
                connectors = db.query(models.Connector).all()
            finally:
                db.close()
        except Exception:
            logger.exception("ConnectorHealth: failed loading connectors")
            return

        due: list[models.Connector] = []
        async with self._lock:
            for connector in connectors:
                snap = self._snapshots.get(connector.id)
                if not snap:
                    due.append(connector)
                    continue
                if snap.next_check_at <= now:
                    due.append(connector)

        checks = 0
        for connector in due:
            if checks >= self.max_checks_per_tick:
                break
            checks += 1
            await self._check_one(connector)

    async def _check_one(self, connector: models.Connector) -> None:
        now = time.time()
        connector_id = int(connector.id)
        connector_type = str(connector.connector_type)
        config: Dict[str, Any] = connector.config or {}

        status = "unknown"
        error = ""
        try:
            instance = get_connector(connector_type, config)
            ok = instance.is_connected()
            status = "up" if ok else "down"
        except Exception as exc:
            status = "down"
            error = str(exc)

        async with self._lock:
            prev = self._snapshots.get(connector_id)
            failures = prev.failures if prev else 0
            if status != "up":
                failures = min(failures + 1, 10)
            else:
                failures = 0

            interval = self.base_interval_s
            if status != "up":
                interval = min(
                    self.max_interval_s,
                    max(self.min_interval_s, self.base_interval_s * (2**failures)),
                )
            next_check = now + interval

            self._snapshots[connector_id] = ConnectorHealthSnapshot(
                connector_id=connector_id,
                connector_type=connector_type,
                status=status,
                checked_at=now,
                next_check_at=next_check,
                failures=failures,
                error=error,
            )
            history = self._history.get(connector_id)
            if history is None:
                history = deque(maxlen=self.history_limit)
                self._history[connector_id] = history
            history.append(
                ConnectorHealthHistoryEntry(
                    connector_id=connector_id,
                    connector_type=connector_type,
                    status=status,
                    checked_at=now,
                    failures=failures,
                    error=error,
                )
            )


connector_health = ConnectorHealthService()
