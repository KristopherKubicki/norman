#!/usr/bin/env python3
"""Run a Mouth revocation drill through the routing action-hold gate."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import crud, models  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.routing.engine import enqueue_routing_job  # noqa: E402
from app.schemas.user import UserCreate  # noqa: E402


DRILL_USER_EMAIL = "mouth-drill@example.com"
DRILL_USERNAME = "mouth_drill"
DRILL_CONNECTOR_NAME = "mouth-revocation-drill-ingress"
DRILL_CONNECTOR_TYPE = "webhook"


@dataclass(frozen=True)
class MouthRevocationDrillResult:
    ran_at: str
    connector_id: int
    previous_kill_switch_level: int
    restored_kill_switch_level: int
    blocked_event_id: int
    blocked_status: str
    blocked_delivery_status: str
    blocked_job_count: int
    restored_event_id: int
    restored_status: str
    restored_delivery_status: str
    restored_job_count: int
    parked_job_count: int
    external_send_attempted: bool = False

    def as_jsonable(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_drill_user(db: Session) -> models.User:
    user = crud.user.get_user_by_email(db, DRILL_USER_EMAIL)
    if user:
        return user
    return crud.user.create_user(
        db,
        UserCreate(
            email=DRILL_USER_EMAIL,
            username=DRILL_USERNAME,
            password="mouth-drill-not-a-secret",
        ),
    )


def _ensure_drill_connector(db: Session, *, user_id: int) -> models.Connector:
    connector = (
        db.query(models.Connector)
        .filter(
            models.Connector.user_id == user_id,
            models.Connector.name == DRILL_CONNECTOR_NAME,
            models.Connector.connector_type == DRILL_CONNECTOR_TYPE,
        )
        .first()
    )
    if connector is None:
        connector = models.Connector(
            user_id=user_id,
            name=DRILL_CONNECTOR_NAME,
            connector_type=DRILL_CONNECTOR_TYPE,
            config={
                "purpose": "Mouth revocation drill ingress only",
                "external_delivery": False,
            },
        )
        db.add(connector)
    else:
        connector.config = {
            "purpose": "Mouth revocation drill ingress only",
            "external_delivery": False,
        }
    db.commit()
    db.refresh(connector)
    return connector


def _event(db: Session, event_id: int) -> models.RoutingEvent:
    event = (
        db.query(models.RoutingEvent).filter(models.RoutingEvent.id == event_id).one()
    )
    return event


def _job_count(db: Session, event_id: int) -> int:
    return (
        db.query(models.RoutingJob)
        .filter(models.RoutingJob.event_id == event_id)
        .count()
    )


def _park_jobs_for_event(db: Session, event_id: int) -> int:
    jobs = (
        db.query(models.RoutingJob).filter(models.RoutingJob.event_id == event_id).all()
    )
    for job in jobs:
        job.status = "done"
        job.last_error = "Mouth drill parked before delivery"
        db.add(job)
    db.commit()
    return len(jobs)


async def run_mouth_revocation_drill(
    db: Session,
    *,
    profile: str = "shared",
    run_id: str | None = None,
) -> MouthRevocationDrillResult:
    user = _ensure_drill_user(db)
    connector = _ensure_drill_connector(db, user_id=user.id)
    run_id = run_id or _utc_now()
    previous_level = int(getattr(settings, "safety_kill_switch_level", 0))

    blocked_payload = {
        "text": f"Mouth revocation drill action-hold probe {run_id}",
        "provenance": "drill",
        "profile": profile,
        "phase": "blocked",
    }
    restored_payload = {
        "text": f"Mouth revocation drill restore probe {run_id}",
        "provenance": "drill",
        "profile": profile,
        "phase": "restored",
    }

    try:
        settings.safety_kill_switch_level = 1
        blocked = await enqueue_routing_job(
            db=db,
            connector=connector,
            normalized=blocked_payload,
            payload=blocked_payload,
        )
        blocked_event_id = int(blocked["event_id"])
        blocked_event = _event(db, blocked_event_id)
        blocked_job_count = _job_count(db, blocked_event_id)
        if blocked_event.delivery_status != "disabled":
            raise RuntimeError(
                "Mouth drill action-hold event was not delivery-disabled"
            )
        if blocked_job_count != 0:
            raise RuntimeError("Mouth drill action-hold event created a routing job")

        settings.safety_kill_switch_level = previous_level
        restored = await enqueue_routing_job(
            db=db,
            connector=connector,
            normalized=restored_payload,
            payload=restored_payload,
            defer_until=datetime.utcnow() + timedelta(days=365),
        )
        restored_event_id = int(restored["event_id"])
        restored_event = _event(db, restored_event_id)
        restored_job_count = _job_count(db, restored_event_id)
        if restored_event.delivery_status != "queued":
            raise RuntimeError("Mouth drill restored event did not remain queued")
        if restored_job_count != 1:
            raise RuntimeError("Mouth drill restored event did not create one job")
        parked_job_count = _park_jobs_for_event(db, restored_event_id)
    finally:
        settings.safety_kill_switch_level = previous_level

    return MouthRevocationDrillResult(
        ran_at=_utc_now(),
        connector_id=int(connector.id),
        previous_kill_switch_level=previous_level,
        restored_kill_switch_level=int(
            getattr(settings, "safety_kill_switch_level", 0)
        ),
        blocked_event_id=blocked_event_id,
        blocked_status=blocked_event.status,
        blocked_delivery_status=blocked_event.delivery_status,
        blocked_job_count=blocked_job_count,
        restored_event_id=restored_event_id,
        restored_status=restored_event.status,
        restored_delivery_status=restored_event.delivery_status,
        restored_job_count=restored_job_count,
        parked_job_count=parked_job_count,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument(
        "--profile",
        default="shared",
        help="Estate policy profile being drilled.",
    )
    parser.add_argument("--run-id", help="Stable run id for tests or replays.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        result = asyncio.run(
            run_mouth_revocation_drill(
                db,
                profile=args.profile,
                run_id=args.run_id,
            )
        )
    finally:
        db.close()

    if args.json:
        print(json.dumps(result.as_jsonable(), indent=2))
    else:
        print(
            "Mouth action-hold drill passed: "
            f"blocked event {result.blocked_event_id}, "
            f"restored event {result.restored_event_id}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
