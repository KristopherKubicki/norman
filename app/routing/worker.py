import asyncio
from datetime import datetime
from typing import Tuple

from app.core.logging import setup_logger
from app.db.session import SessionLocal
from app.crud import routing as routing_crud
from app.routing.engine import process_routing_job, compute_retry_delay
from app.routing.circuit_breaker import CircuitOpen

logger = setup_logger(__name__)


async def _process_due_jobs(stop_event: asyncio.Event, batch_size: int = 10) -> None:
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            jobs = routing_crud.get_due_jobs(db, limit=batch_size)
            if not jobs:
                await asyncio.sleep(1.0)
                continue
            for job in jobs:
                job.status = "processing"
                routing_crud.update_job(db, job)
                try:
                    await process_routing_job(db=db, job=job)
                    job.status = "done"
                    routing_crud.update_job(db, job)
                except CircuitOpen as exc:
                    # Circuit is open: reschedule without burning attempts.
                    job.status = "pending"
                    job.last_error = exc.reason
                    job.next_attempt_at = datetime.utcfromtimestamp(exc.opened_until)
                    routing_crud.update_job(db, job)
                except Exception as exc:
                    job.attempts += 1
                    job.last_error = str(exc)
                    if job.attempts >= job.max_attempts:
                        job.status = "dead"
                        event = (
                            routing_crud.get_event(db, job.event_id)
                            if job.event_id
                            else None
                        )
                        if event:
                            event.status = "dead_letter"
                            event.delivery_status = "dead_letter"
                            event.error = job.last_error
                            routing_crud.update_event(db, event)
                    else:
                        job.status = "pending"
                        delay = compute_retry_delay(job.attempts)
                        job.next_attempt_at = datetime.utcnow() + delay
                    routing_crud.update_job(db, job)
                    logger.exception("Routing job %s failed", job.id)
        finally:
            db.close()


def start_routing_worker() -> Tuple[asyncio.Task, asyncio.Event]:
    stop_event = asyncio.Event()
    task = asyncio.create_task(_process_due_jobs(stop_event))
    return task, stop_event
