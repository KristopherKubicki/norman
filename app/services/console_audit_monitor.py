from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError

from app.core.logging import setup_logger
from app.db.session import SessionLocal
from app import models
from app.services.console_status import fetch_console_audit

logger = setup_logger(__name__)


@dataclass
class ConsoleAuditCursor:
    connector_id: int
    last_seen_at: int = 0
    next_check_at: float = 0.0
    failures: int = 0


def _event_datetime(value: Any) -> datetime:
    try:
        ts = int(value or 0)
    except (TypeError, ValueError):
        ts = 0
    if ts <= 0:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def store_console_audit_events(
    db,
    connector: models.Connector,
    items: list[dict[str, Any]],
    *,
    connector_name: str = "",
) -> tuple[int, int]:
    source_ids = [
        str(item.get("id") or "").strip()
        for item in items
        if str(item.get("id") or "").strip()
    ]
    existing: set[str] = set()
    if source_ids:
        rows = (
            db.query(models.ConsoleAuditEvent.source_event_id)
            .filter(
                models.ConsoleAuditEvent.connector_id == int(connector.id),
                models.ConsoleAuditEvent.source_event_id.in_(source_ids),
            )
            .all()
        )
        existing = {str(row[0] or "") for row in rows}

    imported = 0
    last_seen_at = 0
    default_connector_name = connector_name or str(connector.name or "").strip()
    cfg = dict(connector.config or {})
    default_host_name = urlsplit(str(cfg.get("web_url") or "")).hostname or ""

    for item in items:
        source_event_id = str(item.get("id") or "").strip()
        if not source_event_id or source_event_id in existing:
            try:
                last_seen_at = max(last_seen_at, int(item.get("event_at") or 0))
            except (TypeError, ValueError):
                pass
            continue
        event = models.ConsoleAuditEvent(
            user_id=int(connector.user_id),
            connector_id=int(connector.id),
            connector_name=default_connector_name,
            session_name=str(item.get("session_name") or "").strip(),
            agent_name=str(item.get("agent_name") or "").strip(),
            host_name=str(item.get("host_name") or "").strip() or default_host_name,
            source_event_id=source_event_id,
            event_type=str(item.get("event_type") or "").strip().lower(),
            severity=str(item.get("severity") or "info").strip().lower() or "info",
            actor_type=str(item.get("actor_type") or "system").strip() or "system",
            actor_ip=str(item.get("actor_ip") or "").strip() or None,
            thread_id=str(item.get("thread_id") or "").strip() or None,
            summary=str(item.get("summary") or "").strip(),
            detail=str(item.get("detail") or "").strip() or None,
            payload_json=item.get("payload")
            if isinstance(item.get("payload"), dict)
            else {},
            event_at=_event_datetime(item.get("event_at")),
        )
        try:
            with db.begin_nested():
                db.add(event)
                db.flush()
        except IntegrityError:
            continue
        imported += 1
        existing.add(source_event_id)
        try:
            last_seen_at = max(last_seen_at, int(item.get("event_at") or 0))
        except (TypeError, ValueError):
            pass

    return imported, last_seen_at


class ConsoleAuditMonitorService:
    """Background collector that centralizes per-console audit feeds."""

    def __init__(self) -> None:
        self._cursors: dict[int, ConsoleAuditCursor] = {}
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None

        self.base_interval_s = 45.0
        self.min_interval_s = 15.0
        self.max_interval_s = 10 * 60.0
        self.tick_s = 5.0
        self.max_checks_per_tick = 12
        self.fetch_limit = 200

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="console_audit_monitor")

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

    async def _run_loop(self) -> None:
        assert self._stop_event is not None
        logger.info("ConsoleAuditMonitor: started")
        try:
            while not self._stop_event.is_set():
                await self._tick()
                await asyncio.sleep(self.tick_s)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ConsoleAuditMonitor: loop crashed")
        finally:
            logger.info("ConsoleAuditMonitor: stopped")

    async def _tick(self) -> None:
        now = time.time()
        try:
            db = SessionLocal()
            try:
                connectors = (
                    db.query(models.Connector)
                    .filter(models.Connector.connector_type == "tmux")
                    .all()
                )
            finally:
                db.close()
        except Exception:
            logger.exception("ConsoleAuditMonitor: failed loading connectors")
            return

        due: list[models.Connector] = []
        async with self._lock:
            for connector in connectors:
                cfg = dict(connector.config or {})
                web_url = str(cfg.get("web_url") or "").strip()
                if not web_url:
                    continue
                cursor = self._cursors.get(int(connector.id))
                if not cursor or cursor.next_check_at <= now:
                    due.append(connector)

        checks = 0
        for connector in due:
            if checks >= self.max_checks_per_tick:
                break
            checks += 1
            await self._check_one(connector)

    async def _check_one(self, connector: models.Connector) -> None:
        now = time.time()
        cfg = dict(connector.config or {})
        web_url = str(cfg.get("web_url") or "").strip()
        collector_url = str(cfg.get("collector_url") or "").strip() or web_url
        web_token = str(cfg.get("web_token") or "").strip()
        if not web_url:
            return

        async with self._lock:
            cursor = self._cursors.get(int(connector.id)) or ConsoleAuditCursor(
                connector_id=int(connector.id)
            )
            self._cursors[int(connector.id)] = cursor
            since_ts = max(0, int(cursor.last_seen_at or 0))

        payload = await asyncio.to_thread(
            fetch_console_audit,
            collector_url,
            since_ts=since_ts,
            limit=self.fetch_limit,
            access_token=web_token,
        )

        imported = 0
        last_seen_at = since_ts
        failures = cursor.failures

        if payload.get("reachable"):
            failures = 0
            items = payload.get("items")
            if isinstance(items, list) and items:
                db = SessionLocal()
                try:
                    imported, last_seen_at = store_console_audit_events(
                        db,
                        connector,
                        items,
                        connector_name=str(
                            payload.get("agent_name") or connector.name or ""
                        ),
                    )
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception(
                        "ConsoleAuditMonitor: failed storing audit for connector %s",
                        connector.id,
                    )
                finally:
                    db.close()
            else:
                last_seen_at = since_ts
        else:
            failures = min(failures + 1, 10)

        interval = self.base_interval_s
        if imported:
            interval = self.min_interval_s
        elif not payload.get("reachable"):
            interval = min(
                self.max_interval_s,
                max(self.min_interval_s, self.base_interval_s * (2**failures)),
            )

        async with self._lock:
            self._cursors[int(connector.id)] = ConsoleAuditCursor(
                connector_id=int(connector.id),
                last_seen_at=max(int(last_seen_at or 0), int(since_ts or 0)),
                next_check_at=now + interval,
                failures=failures,
            )


console_audit_monitor = ConsoleAuditMonitorService()
