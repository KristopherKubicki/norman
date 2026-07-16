from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from app.core.logging import setup_logger
from app.db.session import SessionLocal
from app import models
from app.services.console_status import (
    BILLING_URL,
    LIMITS_URL,
    classify_console_credit_assessment,
    fetch_console_status,
)

logger = setup_logger(__name__)


@dataclass
class FleetCreditSnapshot:
    connector_id: int
    connector_name: str
    web_url: str
    issue_code: str
    issue_label: str
    issue_summary: str
    billing_url: str
    limits_url: str
    chat_model: str
    default_speed: str
    recommended_speed: str
    recommended_speed_reason: str
    auth_required: bool
    auth_mode: str
    reachable: bool
    checked_at: float
    next_check_at: float
    usage_tracked: bool = False
    usage_window_seconds: int = 0
    usage_turns: int = 0
    usage_successful_turns: int = 0
    usage_failed_turns: int = 0
    usage_input_tokens: int = 0
    usage_cached_input_tokens: int = 0
    usage_output_tokens: int = 0
    usage_total_tokens: int = 0
    usage_window_turns: int = 0
    usage_window_input_tokens: int = 0
    usage_window_cached_input_tokens: int = 0
    usage_window_output_tokens: int = 0
    usage_window_total_tokens: int = 0
    usage_last_turn_at: int = 0
    usage_last_turn_total_tokens: int = 0
    codex_subscription_capacity_state: str = "unknown"
    codex_subscription_capacity_fresh: bool = False
    codex_subscription_capacity_observed_at: int = 0
    codex_subscription_capacity_percent_left: int = -1
    codex_subscription_capacity_reset_hint: str = ""
    codex_subscription_capacity_eligible: bool = False
    codex_subscription_capacity_tokens_per_hour: int = 0
    codex_subscription_capacity_projected_tokens_to_reset: int = 0
    failures: int = 0


class FleetCreditMonitorService:
    """Background quota/auth watcher for managed console connectors."""

    def __init__(self) -> None:
        self._snapshots: dict[int, FleetCreditSnapshot] = {}
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None

        self.base_interval_s = 120.0
        self.min_interval_s = 30.0
        self.max_interval_s = 15 * 60.0
        self.tick_s = 5.0
        self.max_checks_per_tick = 12

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="fleet_credit_monitor")

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

    async def get_snapshot(self, connector_id: int) -> Optional[FleetCreditSnapshot]:
        async with self._lock:
            snap = self._snapshots.get(connector_id)
            if not snap:
                return None
            return FleetCreditSnapshot(**snap.__dict__)

    async def get_items(
        self, connector_ids: Optional[list[int]] = None
    ) -> list[FleetCreditSnapshot]:
        async with self._lock:
            values = list(self._snapshots.values())
        if connector_ids is not None:
            allowed = set(connector_ids)
            values = [item for item in values if item.connector_id in allowed]
        values.sort(
            key=lambda item: (
                0 if item.issue_code == "needs_billing" else 1,
                0 if item.issue_code == "needs_reauth" else 1,
                0 if item.recommended_speed else 1,
                item.connector_name.lower(),
            )
        )
        return [FleetCreditSnapshot(**item.__dict__) for item in values]

    async def get_summary(
        self, connector_ids: Optional[list[int]] = None
    ) -> dict[str, int]:
        items = await self.get_items(connector_ids)
        return {
            "count": len(items),
            "needs_billing": sum(
                1 for item in items if item.issue_code == "needs_billing"
            ),
            "needs_reauth": sum(
                1 for item in items if item.issue_code == "needs_reauth"
            ),
            "downgrade_candidates": sum(1 for item in items if item.recommended_speed),
            "reachable": sum(1 for item in items if item.reachable),
            "checked": sum(1 for item in items if item.checked_at > 0),
            "usage_tracked": sum(1 for item in items if item.usage_tracked),
            "usage_turns": sum(item.usage_turns for item in items),
            "usage_input_tokens": sum(item.usage_input_tokens for item in items),
            "usage_cached_input_tokens": sum(
                item.usage_cached_input_tokens for item in items
            ),
            "usage_output_tokens": sum(item.usage_output_tokens for item in items),
            "usage_total_tokens": sum(item.usage_total_tokens for item in items),
            "usage_window_turns": sum(item.usage_window_turns for item in items),
            "usage_window_input_tokens": sum(
                item.usage_window_input_tokens for item in items
            ),
            "usage_window_cached_input_tokens": sum(
                item.usage_window_cached_input_tokens for item in items
            ),
            "usage_window_output_tokens": sum(
                item.usage_window_output_tokens for item in items
            ),
            "usage_window_total_tokens": sum(
                item.usage_window_total_tokens for item in items
            ),
            "usage_last_turn_at": max(
                (item.usage_last_turn_at for item in items), default=0
            ),
            "codex_subscription_capacity_available": sum(
                1
                for item in items
                if item.codex_subscription_capacity_state == "available"
                and item.codex_subscription_capacity_fresh
            ),
            "codex_subscription_capacity_eligible": sum(
                1 for item in items if item.codex_subscription_capacity_eligible
            ),
        }

    async def _run_loop(self) -> None:
        assert self._stop_event is not None
        logger.info("FleetCreditMonitor: started")
        try:
            while not self._stop_event.is_set():
                await self._tick()
                await asyncio.sleep(self.tick_s)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("FleetCreditMonitor: loop crashed")
        finally:
            logger.info("FleetCreditMonitor: stopped")

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
            logger.exception("FleetCreditMonitor: failed loading connectors")
            return

        due: list[models.Connector] = []
        async with self._lock:
            for connector in connectors:
                cfg = dict(connector.config or {})
                web_url = str(cfg.get("web_url") or "").strip()
                if not web_url:
                    continue
                snap = self._snapshots.get(int(connector.id))
                if not snap or snap.next_check_at <= now:
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

        status = await asyncio.to_thread(
            fetch_console_status,
            collector_url,
            access_token=web_token,
        )
        assessment = classify_console_credit_assessment(status)

        async with self._lock:
            prev = self._snapshots.get(int(connector.id))
            failures = prev.failures if prev else 0
            if not status.get("reachable"):
                failures = min(failures + 1, 10)
            else:
                failures = 0
            interval = self.base_interval_s
            if assessment.issue_code == "needs_billing":
                interval = self.min_interval_s
            elif assessment.issue_code == "needs_reauth":
                interval = max(self.min_interval_s, 45.0)
            elif not status.get("reachable"):
                interval = min(
                    self.max_interval_s,
                    max(self.min_interval_s, self.base_interval_s * (2**failures)),
                )
            next_check = now + interval
            self._snapshots[int(connector.id)] = FleetCreditSnapshot(
                connector_id=int(connector.id),
                connector_name=str(connector.name or ""),
                web_url=web_url,
                issue_code=assessment.issue_code,
                issue_label=assessment.issue_label,
                issue_summary=assessment.issue_summary,
                billing_url=assessment.billing_url or BILLING_URL,
                limits_url=assessment.limits_url or LIMITS_URL,
                chat_model=str(status.get("chat_model") or ""),
                default_speed=str(status.get("default_speed") or ""),
                recommended_speed=assessment.recommended_speed,
                recommended_speed_reason=assessment.recommended_speed_reason,
                auth_required=bool(status.get("auth_required")),
                auth_mode=str(status.get("auth_mode") or ""),
                reachable=bool(status.get("reachable")),
                checked_at=now,
                next_check_at=next_check,
                usage_tracked=bool(status.get("usage_tracked")),
                usage_window_seconds=int(status.get("usage_window_seconds") or 0),
                usage_turns=int(status.get("usage_turns") or 0),
                usage_successful_turns=int(status.get("usage_successful_turns") or 0),
                usage_failed_turns=int(status.get("usage_failed_turns") or 0),
                usage_input_tokens=int(status.get("usage_input_tokens") or 0),
                usage_cached_input_tokens=int(
                    status.get("usage_cached_input_tokens") or 0
                ),
                usage_output_tokens=int(status.get("usage_output_tokens") or 0),
                usage_total_tokens=int(status.get("usage_total_tokens") or 0),
                usage_window_turns=int(status.get("usage_window_turns") or 0),
                usage_window_input_tokens=int(
                    status.get("usage_window_input_tokens") or 0
                ),
                usage_window_cached_input_tokens=int(
                    status.get("usage_window_cached_input_tokens") or 0
                ),
                usage_window_output_tokens=int(
                    status.get("usage_window_output_tokens") or 0
                ),
                usage_window_total_tokens=int(
                    status.get("usage_window_total_tokens") or 0
                ),
                usage_last_turn_at=int(status.get("usage_last_turn_at") or 0),
                usage_last_turn_total_tokens=int(
                    status.get("usage_last_turn_total_tokens") or 0
                ),
                codex_subscription_capacity_state=str(
                    status.get("codex_subscription_capacity_state") or "unknown"
                ),
                codex_subscription_capacity_fresh=bool(
                    status.get("codex_subscription_capacity_fresh")
                ),
                codex_subscription_capacity_observed_at=int(
                    status.get("codex_subscription_capacity_observed_at") or 0
                ),
                codex_subscription_capacity_percent_left=int(
                    status.get("codex_subscription_capacity_percent_left")
                    if status.get("codex_subscription_capacity_percent_left")
                    is not None
                    else -1
                ),
                codex_subscription_capacity_reset_hint=str(
                    status.get("codex_subscription_capacity_reset_hint") or ""
                ),
                codex_subscription_capacity_eligible=bool(
                    status.get("codex_subscription_capacity_eligible")
                ),
                codex_subscription_capacity_tokens_per_hour=int(
                    status.get("codex_subscription_capacity_tokens_per_hour") or 0
                ),
                codex_subscription_capacity_projected_tokens_to_reset=int(
                    status.get("codex_subscription_capacity_projected_tokens_to_reset")
                    or 0
                ),
                failures=failures,
            )


fleet_credit_monitor = FleetCreditMonitorService()
