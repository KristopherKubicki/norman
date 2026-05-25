from typing import List, Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.routing import RoutingRule, RoutingEvent, RoutingJob
from app.schemas.routing import RoutingRuleCreate, RoutingRuleUpdate


def get_rule(db: Session, rule_id: int) -> Optional[RoutingRule]:
    return db.query(RoutingRule).filter(RoutingRule.id == rule_id).first()


def get_rules_by_user(db: Session, user_id: int) -> List[RoutingRule]:
    return db.query(RoutingRule).filter(RoutingRule.user_id == user_id).all()


def create_rule(
    db: Session, *, user_id: int, rule_in: RoutingRuleCreate
) -> RoutingRule:
    rule = RoutingRule(user_id=user_id, **rule_in.dict())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def update_rule(
    db: Session, *, rule: RoutingRule, rule_in: RoutingRuleUpdate
) -> RoutingRule:
    for field, value in rule_in.dict(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


def delete_rule(db: Session, rule: RoutingRule) -> None:
    db.delete(rule)
    db.commit()


def create_event(db: Session, event: RoutingEvent) -> RoutingEvent:
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def update_event(db: Session, event: RoutingEvent) -> RoutingEvent:
    db.commit()
    db.refresh(event)
    return event


def get_event(db: Session, event_id: int) -> Optional[RoutingEvent]:
    return db.query(RoutingEvent).filter(RoutingEvent.id == event_id).first()


def get_events_by_user(
    db: Session, user_id: int, *, limit: int = 200
) -> List[RoutingEvent]:
    return (
        db.query(RoutingEvent)
        .filter(RoutingEvent.user_id == user_id)
        .order_by(RoutingEvent.id.desc())
        .limit(limit)
        .all()
    )


def create_job(db: Session, job: RoutingJob) -> RoutingJob:
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job(db: Session, job: RoutingJob) -> RoutingJob:
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: int) -> Optional[RoutingJob]:
    return db.query(RoutingJob).filter(RoutingJob.id == job_id).first()


def get_latest_job_for_event(db: Session, event_id: int) -> Optional[RoutingJob]:
    return (
        db.query(RoutingJob)
        .filter(RoutingJob.event_id == event_id)
        .order_by(RoutingJob.id.desc())
        .first()
    )


def get_job_by_user(
    db: Session, user_id: int, job_id: int
) -> Tuple[Optional[RoutingJob], Optional[RoutingEvent]]:
    row = (
        db.query(RoutingJob, RoutingEvent)
        .join(RoutingEvent, RoutingJob.event_id == RoutingEvent.id)
        .filter(RoutingJob.id == job_id)
        .filter(RoutingEvent.user_id == user_id)
        .first()
    )
    if not row:
        return (None, None)
    return row


def get_jobs_by_user(
    db: Session,
    user_id: int,
    *,
    limit: int = 100,
    status: Optional[str] = None,
    include_done: bool = False,
) -> List[Tuple[RoutingJob, RoutingEvent]]:
    query = (
        db.query(RoutingJob, RoutingEvent)
        .join(RoutingEvent, RoutingJob.event_id == RoutingEvent.id)
        .filter(RoutingEvent.user_id == user_id)
    )
    normalized_status = (status or "").strip().lower()
    if normalized_status and normalized_status != "all":
        query = query.filter(RoutingJob.status == normalized_status)
    elif not include_done:
        query = query.filter(RoutingJob.status != "done")
    return query.order_by(RoutingJob.id.desc()).limit(limit).all()


def retry_job(
    db: Session,
    job: RoutingJob,
    *,
    event: Optional[RoutingEvent] = None,
) -> Tuple[RoutingJob, Optional[RoutingEvent]]:
    was_dead = job.status == "dead"
    job.status = "pending"
    if was_dead:
        job.attempts = 0
    job.last_error = None
    job.next_attempt_at = datetime.utcnow()
    db.add(job)
    if event:
        event.status = "queued"
        event.delivery_status = "queued"
        event.error = None
        event.delivery_error = None
        db.add(event)
    db.commit()
    db.refresh(job)
    if event:
        db.refresh(event)
    return (job, event)


def get_due_jobs(db: Session, *, limit: int = 10) -> List[RoutingJob]:
    return (
        db.query(RoutingJob)
        .filter(RoutingJob.status == "pending")
        .filter(RoutingJob.next_attempt_at <= datetime.utcnow())
        .order_by(RoutingJob.next_attempt_at.asc(), RoutingJob.id.asc())
        .limit(limit)
        .all()
    )
