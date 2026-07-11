from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import setup_logger
from app.db import session as db_session
from app.services.console_runtime.kernel import InvalidTransitionError
from app.services.console_runtime.store import DbConsoleRuntimeStore
from app.services.console_runtime.worker import (
    ConsoleRuntimeRunOptions,
    DEFAULT_GOAL_PHASE_SEQUENCE,
    DbConsoleRuntimeWorker,
)

logger = setup_logger(__name__)

LIVE_EXECUTION_CONFIRMATION = "ENABLE LIVE RUNTIME"


@dataclass
class ConsoleRuntimeWorkerSnapshot:
    enabled: bool
    running: bool
    tick_count: int = 0
    jobs_started: int = 0
    jobs_completed: int = 0
    failures: int = 0
    last_job_id: str = ""
    last_error: str = ""


class ConsoleRuntimeWorkerService:
    """Background poller that leases queued console-runtime jobs."""

    def __init__(
        self,
        *,
        store: DbConsoleRuntimeStore | None = None,
        worker: DbConsoleRuntimeWorker | None = None,
    ) -> None:
        self.store = store or DbConsoleRuntimeStore()
        self.worker = worker or DbConsoleRuntimeWorker(self.store)
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._lock = asyncio.Lock()
        self._snapshot = ConsoleRuntimeWorkerSnapshot(
            enabled=bool(getattr(settings, "console_runtime_worker_enabled", False)),
            running=False,
        )

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._run_loop(), name="console_runtime_worker"
        )

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
        async with self._lock:
            self._snapshot.running = False

    async def snapshot(self) -> ConsoleRuntimeWorkerSnapshot:
        async with self._lock:
            return ConsoleRuntimeWorkerSnapshot(**self._snapshot.__dict__)

    async def status_payload(self, *, runnable_count: int = 0) -> dict:
        snapshot = await self.snapshot()
        return {
            "snapshot": asdict(snapshot),
            "config": self.config_payload(),
            "runnable_count": max(0, int(runnable_count or 0)),
            "live_execution_confirmation": LIVE_EXECUTION_CONFIRMATION,
        }

    def config_payload(self) -> dict:
        return {
            "enabled": bool(getattr(settings, "console_runtime_worker_enabled", False)),
            "dry_run": bool(getattr(settings, "console_runtime_worker_dry_run", True)),
            "live_execution_enabled": bool(
                getattr(
                    settings, "console_runtime_worker_live_execution_enabled", False
                )
            ),
            "continuous_enabled": bool(
                getattr(settings, "console_runtime_worker_continuous_enabled", False)
            ),
            "max_steps": self._max_steps(),
            "max_runtime_seconds": self._max_runtime_seconds(),
            "goal_phase_sequence": self._goal_phase_sequence(),
            "tick_seconds": self._tick_seconds(),
            "batch_size": self._batch_size(),
            "worker_id": str(
                getattr(settings, "console_runtime_worker_id", "")
                or "runtime-background-worker"
            ),
        }

    async def configure(
        self,
        *,
        enabled: bool | None = None,
        dry_run: bool | None = None,
        live_execution_enabled: bool | None = None,
        continuous_enabled: bool | None = None,
        max_steps: int | None = None,
        max_runtime_seconds: int | None = None,
        goal_phase_sequence: list[str] | None = None,
        tick_seconds: float | None = None,
        batch_size: int | None = None,
        worker_id: str = "",
        confirm_live_execution: str = "",
        reset_counters: bool = False,
    ) -> None:
        live_requested = (dry_run is False) or (live_execution_enabled is True)
        if live_requested and confirm_live_execution != LIVE_EXECUTION_CONFIRMATION:
            raise ValueError(
                "Live runtime execution requires confirmation phrase "
                f"{LIVE_EXECUTION_CONFIRMATION!r}"
            )

        if enabled is not None:
            settings.console_runtime_worker_enabled = bool(enabled)
        if dry_run is not None:
            settings.console_runtime_worker_dry_run = bool(dry_run)
        if live_execution_enabled is not None:
            settings.console_runtime_worker_live_execution_enabled = bool(
                live_execution_enabled
            )
        if continuous_enabled is not None:
            settings.console_runtime_worker_continuous_enabled = bool(
                continuous_enabled
            )
        if max_steps is not None:
            settings.console_runtime_worker_max_steps = self._coerce_max_steps(
                max_steps
            )
        if max_runtime_seconds is not None:
            settings.console_runtime_worker_max_runtime_seconds = (
                self._coerce_max_runtime_seconds(max_runtime_seconds)
            )
        if goal_phase_sequence is not None:
            settings.console_runtime_worker_goal_phase_sequence = (
                self._coerce_goal_phase_sequence(goal_phase_sequence)
            )
        if tick_seconds is not None:
            settings.console_runtime_worker_tick_seconds = self._coerce_tick_seconds(
                tick_seconds
            )
        if batch_size is not None:
            settings.console_runtime_worker_batch_size = self._coerce_batch_size(
                batch_size
            )
        if worker_id:
            settings.console_runtime_worker_id = str(worker_id).strip()
        if reset_counters:
            async with self._lock:
                self._snapshot.tick_count = 0
                self._snapshot.jobs_started = 0
                self._snapshot.jobs_completed = 0
                self._snapshot.failures = 0
                self._snapshot.last_job_id = ""
                self._snapshot.last_error = ""

        if bool(getattr(settings, "console_runtime_worker_enabled", False)):
            await self.start()
        else:
            await self.stop()

    async def _run_loop(self) -> None:
        assert self._stop_event is not None
        async with self._lock:
            self._snapshot.enabled = True
            self._snapshot.running = True
        logger.info("ConsoleRuntimeWorker: started")
        try:
            while not self._stop_event.is_set():
                await self._tick()
                await asyncio.sleep(self._tick_seconds())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ConsoleRuntimeWorker: loop crashed")
        finally:
            async with self._lock:
                self._snapshot.running = False
            logger.info("ConsoleRuntimeWorker: stopped")

    async def _tick(self) -> int:
        if not bool(getattr(settings, "console_runtime_worker_enabled", False)):
            async with self._lock:
                self._snapshot.enabled = False
                self._snapshot.running = False
            return 0

        batch_size = self._batch_size()
        processed = 0
        db = db_session.SessionLocal()
        try:
            items = self.store.list_runnable_jobs(db, limit=batch_size)
            for user_id, job in items:
                try:
                    await asyncio.to_thread(
                        self._run_job_once,
                        user_id,
                        job.job_id,
                    )
                    processed += 1
                    async with self._lock:
                        self._snapshot.jobs_started += 1
                        self._snapshot.jobs_completed += 1
                        self._snapshot.last_job_id = job.job_id
                        self._snapshot.last_error = ""
                except InvalidTransitionError:
                    logger.info(
                        "ConsoleRuntimeWorker: skipped job with invalid transition",
                        extra={"job_id": job.job_id},
                    )
                except Exception as exc:
                    async with self._lock:
                        self._snapshot.failures += 1
                        self._snapshot.last_job_id = job.job_id
                        self._snapshot.last_error = str(exc)
                    logger.exception(
                        "ConsoleRuntimeWorker: job failed",
                        extra={"job_id": job.job_id},
                    )
        finally:
            db.close()

        async with self._lock:
            self._snapshot.enabled = True
            self._snapshot.running = True
            self._snapshot.tick_count += 1
        return processed

    def _run_job_once(self, user_id: int, job_id: str) -> None:
        db = db_session.SessionLocal()
        try:
            job = self.store.get_job(db, user_id=user_id, job_id=job_id)
            options = self._run_options(job=job)
            if options.continuous:
                self.worker.run_continuous(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    options=options,
                )
            else:
                self.worker.run_once(
                    db,
                    user_id=user_id,
                    job_id=job_id,
                    options=options,
                )
        finally:
            db.close()

    def _run_options(self, *, job=None) -> ConsoleRuntimeRunOptions:
        route_policy = dict(getattr(getattr(job, "contract", None), "route_policy", {}))
        contract_metadata = dict(
            getattr(getattr(job, "contract", None), "metadata", {})
        )
        job_metadata = dict(getattr(job, "metadata", {}))
        metadata = {**job_metadata, **contract_metadata}
        continuous_candidate = self._job_flag(
            route_policy,
            metadata,
            "continuous_goal_candidate",
            default=False,
        )
        continuous_enabled = (
            bool(getattr(settings, "console_runtime_worker_continuous_enabled", False))
            or continuous_candidate
        )
        return ConsoleRuntimeRunOptions(
            worker_id=str(
                getattr(settings, "console_runtime_worker_id", "")
                or "runtime-background-worker"
            ),
            dry_run=bool(getattr(settings, "console_runtime_worker_dry_run", True)),
            live_execution_approved=bool(
                getattr(
                    settings, "console_runtime_worker_live_execution_enabled", False
                )
            ),
            continuous=continuous_enabled,
            max_steps=self._job_int(
                route_policy,
                metadata,
                "max_steps",
                self._max_steps(),
            ),
            max_runtime_seconds=self._job_int(
                route_policy,
                metadata,
                "max_runtime_seconds",
                self._max_runtime_seconds(),
            ),
            local_token_budget=self._job_int(
                route_policy,
                metadata,
                "local_token_budget",
                0,
            ),
            cloud_token_budget=self._job_int(
                route_policy,
                metadata,
                "cloud_token_budget",
                0,
            ),
            goal_phase_sequence=self._job_goal_phase_sequence(route_policy, metadata),
            include_capabilities=not bool(
                getattr(settings, "console_runtime_worker_dry_run", True)
            ),
            route_policy=route_policy,
            metadata={
                "source": "runtime_background_worker",
                "job_source": str(metadata.get("source") or ""),
                "tui_backend": str(metadata.get("tui_backend") or ""),
                "kernel_execution_candidate": self._job_flag(
                    route_policy,
                    metadata,
                    "kernel_execution_candidate",
                    default=False,
                ),
            },
        )

    def _tick_seconds(self) -> float:
        return self._coerce_tick_seconds(
            getattr(settings, "console_runtime_worker_tick_seconds", 5.0)
        )

    def _batch_size(self) -> int:
        return self._coerce_batch_size(
            getattr(settings, "console_runtime_worker_batch_size", 1)
        )

    def _max_steps(self) -> int:
        return self._coerce_max_steps(
            getattr(settings, "console_runtime_worker_max_steps", 4)
        )

    def _max_runtime_seconds(self) -> int:
        return self._coerce_max_runtime_seconds(
            getattr(settings, "console_runtime_worker_max_runtime_seconds", 1800)
        )

    def _goal_phase_sequence(self) -> list[str]:
        return self._coerce_goal_phase_sequence(
            getattr(
                settings,
                "console_runtime_worker_goal_phase_sequence",
                ["plan", "work", "verify"],
            )
        )

    def _coerce_tick_seconds(self, value: object) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = 5.0
        return max(0.25, min(parsed, 300.0))

    def _coerce_batch_size(self, value: object) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 1
        return max(1, min(parsed, 25))

    def _coerce_max_steps(self, value: object) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 4
        return max(1, min(parsed, 50))

    def _coerce_max_runtime_seconds(self, value: object) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 1800
        return max(30, min(parsed, 7200))

    def _coerce_goal_phase_sequence(self, value: object) -> list[str]:
        if isinstance(value, str):
            values = value.split(",")
        elif isinstance(value, list):
            values = value
        else:
            values = []
        phases: list[str] = []
        for item in values:
            phase = str(item or "").strip().lower()
            if phase and phase not in phases:
                phases.append(phase)
        return phases or list(DEFAULT_GOAL_PHASE_SEQUENCE)

    def _job_goal_phase_sequence(
        self,
        route_policy: dict[str, Any],
        metadata: dict[str, Any],
    ) -> list[str]:
        return self._coerce_goal_phase_sequence(
            route_policy.get("goal_phase_sequence")
            or metadata.get("goal_phase_sequence")
            or self._goal_phase_sequence()
        )

    def _job_int(
        self,
        route_policy: dict[str, Any],
        metadata: dict[str, Any],
        key: str,
        default: int,
    ) -> int:
        raw = route_policy.get(key, metadata.get(key, default))
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            parsed = int(default or 0)
        return max(0, parsed)

    def _job_flag(
        self,
        route_policy: dict[str, Any],
        metadata: dict[str, Any],
        key: str,
        *,
        default: bool = False,
    ) -> bool:
        raw = route_policy.get(key, metadata.get(key))
        if isinstance(raw, bool):
            return raw
        clean = str(raw or "").strip().lower()
        if not clean:
            return default
        if clean in {"1", "true", "yes", "on", "enabled", "force"}:
            return True
        if clean in {"0", "false", "no", "off", "disabled"}:
            return False
        return default


console_runtime_worker_service = ConsoleRuntimeWorkerService()
