"""Passive UDP listener service.

Goal: get to "listening fast" without enabling actions.

Many cloud integrations are webhook-based (HTTP). For local network telemetry
(SNMP traps, syslog), Norman needs a long-running UDP listener.

This service binds unprivileged ports by default (SNMP 1162, syslog 1514)
and converts packets into RoutingEvents (and RoutingJobs unless ingest-only
mode is enabled).

Notes:
- This is intentionally conservative: it only starts listeners for connector
  types that are known to be passive UDP sensors.
- We dedupe by (type, host, port). Multiple connectors cannot share a bind.
"""

from __future__ import annotations

import asyncio
import os
import sys
import socket
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from app.core.logging import setup_logger
from app.db.session import SessionLocal
from app import models
from app.connectors.connector_utils import get_connector
from app.routing.engine import enqueue_routing_job

logger = setup_logger(__name__)


_PASSIVE_UDP_TYPES = {
    "snmp",
    "syslog",
}


@dataclass
class _BindKey:
    connector_type: str
    host: str
    port: int


class PassiveUdpListenerService:
    def __init__(self) -> None:
        self._tasks: Dict[_BindKey, asyncio.Task] = {}
        self._sockets: Dict[_BindKey, socket.socket] = {}
        self._stop: Optional[asyncio.Event] = None
        self._scan_task: Optional[asyncio.Task] = None
        self.scan_interval_s = 10.0

    async def start(self) -> None:
        disable_env = os.environ.get("DISABLE_PASSIVE_UDP_LISTENERS", "").lower()
        if disable_env in {"1", "true", "yes"}:
            return
        if "pytest" in sys.modules:
            return
        if self._scan_task and not self._scan_task.done():
            return
        self._stop = asyncio.Event()
        self._scan_task = asyncio.create_task(
            self._scan_loop(), name="passive_udp_scan"
        )
        logger.info("PassiveUdpListeners: started")

    async def stop(self) -> None:
        if not self._stop:
            return
        self._stop.set()
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
        self._scan_task = None

        for key, task in list(self._tasks.items()):
            task.cancel()
        for key, task in list(self._tasks.items()):
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._tasks.clear()

        for sock in list(self._sockets.values()):
            try:
                sock.close()
            except Exception:
                pass
        self._sockets.clear()
        logger.info("PassiveUdpListeners: stopped")

    async def _scan_loop(self) -> None:
        assert self._stop is not None
        try:
            while not self._stop.is_set():
                await self._reconcile()
                await asyncio.sleep(self.scan_interval_s)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("PassiveUdpListeners: scan loop crashed")

    def _desired_bind_key(self, connector: models.Connector) -> Optional[_BindKey]:
        ctype = (connector.connector_type or "").strip().lower()
        if ctype not in _PASSIVE_UDP_TYPES:
            return None
        cfg = connector.config or {}
        host = str(cfg.get("host") or "0.0.0.0").strip() or "0.0.0.0"
        port = int(cfg.get("port") or (1162 if ctype == "snmp" else 1514))
        listen = cfg.get("listen")
        if listen is False:
            return None
        return _BindKey(connector_type=ctype, host=host, port=port)

    async def _reconcile(self) -> None:
        db = SessionLocal()
        try:
            connectors = db.query(models.Connector).all()
        finally:
            db.close()

        desired: Dict[_BindKey, int] = {}
        for c in connectors:
            key = self._desired_bind_key(c)
            if not key:
                continue
            # One listener per bind. If multiple connectors collide, keep the first.
            desired.setdefault(key, int(c.id))

        for key, connector_id in desired.items():
            if key in self._tasks and not self._tasks[key].done():
                continue
            await self._start_listener(key=key, connector_id=connector_id)

        # Stop listeners that are no longer desired.
        for key in list(self._tasks.keys()):
            if key in desired:
                continue
            task = self._tasks.pop(key)
            task.cancel()
            sock = self._sockets.pop(key, None)
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

    async def _start_listener(self, *, key: _BindKey, connector_id: int) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((key.host, key.port))
            sock.setblocking(False)
        except OSError as exc:
            logger.warning(
                "PassiveUdpListeners: failed to bind %s %s:%s (%s)",
                key.connector_type,
                key.host,
                key.port,
                exc,
            )
            return

        self._sockets[key] = sock
        task = asyncio.create_task(
            self._listener_loop(key=key, connector_id=connector_id, sock=sock),
            name=f"passive_udp_{key.connector_type}_{key.host}_{key.port}",
        )
        self._tasks[key] = task
        logger.info(
            "PassiveUdpListeners: listening %s on %s:%s (connector %s)",
            key.connector_type,
            key.host,
            key.port,
            connector_id,
        )

    async def _listener_loop(
        self, *, key: _BindKey, connector_id: int, sock: socket.socket
    ) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                data, addr = await loop.sock_recvfrom(sock, 8192)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(0.1)
                continue

            # Load connector row and normalize via connector implementation.
            db = SessionLocal()
            try:
                connector = (
                    db.query(models.Connector)
                    .filter(models.Connector.id == connector_id)
                    .first()
                )
                if not connector:
                    continue
                cfg = connector.config or {}
                instance = get_connector(key.connector_type, cfg)
                text = data.decode("utf-8", "ignore")
                normalized = instance.process_incoming({"text": text, "addr": addr})
                if asyncio.iscoroutine(normalized):
                    normalized = await normalized
                await enqueue_routing_job(
                    db=db,
                    connector=connector,
                    normalized=normalized if isinstance(normalized, dict) else None,
                    payload={
                        "text": text,
                        "addr": {"ip": addr[0], "port": addr[1]},
                        "connector_type": key.connector_type,
                    },
                )
            except Exception:
                logger.exception(
                    "PassiveUdpListeners: failed processing %s packet (connector %s)",
                    key.connector_type,
                    connector_id,
                )
            finally:
                db.close()


passive_udp_listeners = PassiveUdpListenerService()
