from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app import models
from app.core.config import get_settings
from app.crud import routing as routing_crud
from app.schemas.routing import (
    RoutingRuleCreate,
    RoutingRuleUpdate,
    RoutingRuleOut,
    RoutingEventOut,
    RoutingJobOut,
    RoutingTraceOut,
    RoutingTraceRule,
    RoutingTraceJob,
    RoutingTraceBot,
    RoutingTraceConnector,
    RoutingSimulationRequest,
    RoutingSimulationResponse,
    RoutingSimulationMatch,
)
import re

router = APIRouter()


def _job_to_out(
    job: models.RoutingJob, event: Optional[models.RoutingEvent]
) -> RoutingJobOut:
    return RoutingJobOut(
        id=job.id,
        event_id=job.event_id,
        connector_id=job.connector_id,
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        next_attempt_at=job.next_attempt_at,
        last_error=job.last_error,
        created_at=job.created_at,
        updated_at=job.updated_at,
        event_status=event.status if event else None,
        event_delivery_status=event.delivery_status if event else None,
        event_delivery_error=event.delivery_error if event else None,
        event_connector_id=event.connector_id if event else None,
        event_connector_type=event.connector_type if event else None,
        destination_connector_id=event.destination_connector_id if event else None,
        destination_connector_type=event.destination_connector_type if event else None,
        bot_id=event.bot_id if event else None,
        rule_id=event.rule_id if event else None,
        message_text=event.message_text if event else None,
    )


def _connector_trace(
    connector: Optional[models.Connector],
    *,
    connector_id: Optional[int] = None,
    connector_type: Optional[str] = None,
) -> Optional[RoutingTraceConnector]:
    if connector is None and connector_id is None and connector_type is None:
        return None
    return RoutingTraceConnector(
        id=connector.id if connector else connector_id,
        name=connector.name if connector else None,
        connector_type=connector.connector_type if connector else connector_type,
    )


def _rule_trace(rule: Optional[models.RoutingRule]) -> Optional[RoutingTraceRule]:
    if rule is None:
        return None
    return RoutingTraceRule(
        id=rule.id,
        name=rule.name,
        connector_id=rule.connector_id,
        connector_type=rule.connector_type,
        destination_connector_id=rule.destination_connector_id,
        bot_id=rule.bot_id,
        match_type=rule.match_type,
        match_value=rule.match_value,
        priority=rule.priority,
        is_active=bool(rule.is_active),
    )


def _bot_trace(bot: Optional[models.Bot]) -> Optional[RoutingTraceBot]:
    if bot is None:
        return None
    return RoutingTraceBot(
        id=bot.id,
        name=bot.name,
        session_id=bot.session_id,
        gpt_model=bot.gpt_model,
    )


def _trace_job(job: Optional[models.RoutingJob]) -> Optional[RoutingTraceJob]:
    if job is None:
        return None
    return RoutingTraceJob(
        id=job.id,
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        next_attempt_at=job.next_attempt_at,
        last_error=job.last_error,
    )


def _rule_match_reason(rule: models.RoutingRule) -> str:
    if rule.match_type == "all":
        return "Rule matched all messages."
    if rule.match_type == "contains":
        return f'Rule matched because the message contained "{rule.match_value or ""}".'
    if rule.match_type == "regex":
        return f'Rule matched regex "{rule.match_value or ""}".'
    if rule.match_type == "passive":
        if rule.match_value:
            return f'Rule matched passive source "{rule.match_value}".'
        return "Rule matched passive traffic."
    return f'Rule matched via "{rule.match_type}".'


def _delivery_status_reason(event: models.RoutingEvent) -> str:
    status = (event.delivery_status or "").strip().lower()
    if status == "sent":
        return "Delivery succeeded."
    if status == "queued":
        return "Delivery is queued."
    if status == "failed":
        return "Delivery failed."
    if status == "dead_letter":
        return "Delivery exhausted retries and moved to dead letter."
    if status == "needs_approval":
        return "Delivery is waiting on approval."
    if status == "blocked_operator_takeover":
        return (
            "Delivery is blocked because the target is under manual operator control."
        )
    if status == "blocked":
        return "Delivery was blocked by policy."
    if status == "blocked_budget":
        return "Delivery hit its allowed budget."
    if status == "circuit_open":
        return "Delivery is paused because the connector circuit breaker is open."
    if status == "disabled":
        return "Delivery is disabled by safety controls."
    if status:
        return f'Delivery status is "{status}".'
    return "Delivery state is unknown."


def _trace_explanation(
    event: models.RoutingEvent,
    *,
    source_connector: Optional[models.Connector],
    destination_connector: Optional[models.Connector],
    rule: Optional[models.RoutingRule],
    bot: Optional[models.Bot],
    latest_job: Optional[models.RoutingJob],
) -> list[str]:
    details: list[str] = []
    source_name = (
        source_connector.name
        if source_connector and source_connector.name
        else event.connector_type or f"connector {event.connector_id}"
    )
    details.append(f"Received event on {source_name}.")
    if rule is not None:
        details.append(_rule_match_reason(rule))
        details.append(
            f'Rule priority {rule.priority} selected bot "{bot.name if bot else rule.bot_id}".'
        )
    elif bot is not None:
        details.append(
            f'No explicit routing rule was recorded; fallback bot "{bot.name}" handled the event.'
        )
    else:
        details.append("No bot or routing rule was recorded for this event.")
    if destination_connector is not None:
        details.append(
            f"Delivery targeted {destination_connector.name or destination_connector.connector_type or destination_connector.id}."
        )
    elif source_connector is not None:
        details.append(
            f"Delivery used the source connector {source_connector.name or source_connector.connector_type or source_connector.id}."
        )
    details.append(_delivery_status_reason(event))
    if event.delivery_error:
        details.append(f"Delivery error: {event.delivery_error}.")
    elif event.error:
        details.append(f"Processing error: {event.error}.")
    if latest_job is not None:
        details.append(
            f"Latest job is {latest_job.status} after {latest_job.attempts}/{latest_job.max_attempts} attempts."
        )
        if latest_job.last_error and latest_job.last_error != event.delivery_error:
            details.append(f"Latest job error: {latest_job.last_error}.")
    return details


def _rule_matches_text(
    text: str,
    match_type: str,
    match_value: str | None,
    *,
    connector_type: str | None = None,
    signal_class: str | None = None,
    passive_source: str | None = None,
) -> bool:
    if match_type == "all":
        return True
    if match_type == "passive":
        if (signal_class or "").strip().lower() != "passive":
            return False
        if not match_value:
            return True
        needle = match_value.strip().lower()
        return needle in {
            (passive_source or "").strip().lower(),
            (connector_type or "").strip().lower(),
            "passive",
        }
    if not text:
        return False
    if match_type == "contains":
        return bool(match_value) and match_value.lower() in text.lower()
    if match_type == "regex":
        if not match_value:
            return False
        try:
            return re.search(match_value, text) is not None
        except re.error:
            return False
    return False


@router.get("/routing/rules", response_model=List[RoutingRuleOut])
async def list_routing_rules(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> List[RoutingRuleOut]:
    return routing_crud.get_rules_by_user(db, current_user.id)


@router.post("/routing/rules", response_model=RoutingRuleOut)
async def create_routing_rule(
    rule: RoutingRuleCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> RoutingRuleOut:
    app_settings = get_settings()
    if getattr(app_settings, "safety_shadow_rules_default", False):
        rule = rule.copy(update={"is_active": False})

    if (
        rule.connector_id
        and rule.destination_connector_id
        and int(rule.connector_id) == int(rule.destination_connector_id)
    ):
        raise HTTPException(
            status_code=400,
            detail="Source and destination connectors must be different",
        )
    if rule.destination_connector_id:
        dest = (
            db.query(models.Connector)
            .filter(models.Connector.id == rule.destination_connector_id)
            .first()
        )
        if not dest or dest.user_id != current_user.id:
            raise HTTPException(
                status_code=404, detail="Destination connector not found"
            )
    return routing_crud.create_rule(db, user_id=current_user.id, rule_in=rule)


@router.put("/routing/rules/{rule_id}", response_model=RoutingRuleOut)
async def update_routing_rule(
    rule_id: int,
    rule: RoutingRuleUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> RoutingRuleOut:
    existing = routing_crud.get_rule(db, rule_id)
    if not existing or existing.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Rule not found")

    if rule.destination_connector_id is not None:
        if not rule.destination_connector_id:
            rule.destination_connector_id = None
        else:
            dest = (
                db.query(models.Connector)
                .filter(models.Connector.id == rule.destination_connector_id)
                .first()
            )
            if not dest or dest.user_id != current_user.id:
                raise HTTPException(
                    status_code=404, detail="Destination connector not found"
                )

    source_connector_id = (
        rule.connector_id if rule.connector_id is not None else existing.connector_id
    )
    destination_connector_id = (
        rule.destination_connector_id
        if rule.destination_connector_id is not None
        else existing.destination_connector_id
    )
    if (
        source_connector_id
        and destination_connector_id
        and int(source_connector_id) == int(destination_connector_id)
    ):
        raise HTTPException(
            status_code=400,
            detail="Source and destination connectors must be different",
        )

    return routing_crud.update_rule(db, rule=existing, rule_in=rule)


@router.delete("/routing/rules/{rule_id}")
async def delete_routing_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> dict:
    existing = routing_crud.get_rule(db, rule_id)
    if not existing or existing.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Rule not found")
    routing_crud.delete_rule(db, existing)
    return {"status": "success"}


@router.get("/routing/events", response_model=List[RoutingEventOut])
async def list_routing_events(
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> List[RoutingEventOut]:
    return routing_crud.get_events_by_user(db, current_user.id, limit=limit)


@router.get("/routing/events/{event_id}", response_model=RoutingEventOut)
async def get_routing_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> RoutingEventOut:
    event = routing_crud.get_event(db, event_id)
    if not event or event.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.get("/routing/events/{event_id}/trace", response_model=RoutingTraceOut)
async def get_routing_event_trace(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> RoutingTraceOut:
    event = routing_crud.get_event(db, event_id)
    if not event or event.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Event not found")

    source_connector = (
        db.query(models.Connector)
        .filter(models.Connector.id == event.connector_id)
        .filter(models.Connector.user_id == current_user.id)
        .first()
        if event.connector_id
        else None
    )
    destination_connector = (
        db.query(models.Connector)
        .filter(models.Connector.id == event.destination_connector_id)
        .filter(models.Connector.user_id == current_user.id)
        .first()
        if event.destination_connector_id
        else None
    )
    bot = (
        db.query(models.Bot)
        .filter(models.Bot.id == event.bot_id)
        .filter(models.Bot.user_id == current_user.id)
        .first()
        if event.bot_id
        else None
    )
    rule = (
        db.query(models.RoutingRule)
        .filter(models.RoutingRule.id == event.rule_id)
        .filter(models.RoutingRule.user_id == current_user.id)
        .first()
        if event.rule_id
        else None
    )
    latest_job = routing_crud.get_latest_job_for_event(db, event.id)
    decision = "matched_rule" if rule else ("fallback_bot" if bot else "no_bot")
    return RoutingTraceOut(
        event=RoutingEventOut.from_orm(event),
        source_connector=_connector_trace(
            source_connector,
            connector_id=event.connector_id,
            connector_type=event.connector_type,
        ),
        destination_connector=_connector_trace(
            destination_connector,
            connector_id=event.destination_connector_id,
            connector_type=event.destination_connector_type,
        ),
        bot=_bot_trace(bot),
        rule=_rule_trace(rule),
        latest_job=_trace_job(latest_job),
        decision=decision,
        explanation=_trace_explanation(
            event,
            source_connector=source_connector,
            destination_connector=destination_connector,
            rule=rule,
            bot=bot,
            latest_job=latest_job,
        ),
    )


@router.get("/routing/jobs", response_model=List[RoutingJobOut])
async def list_routing_jobs(
    limit: int = 100,
    status: Optional[str] = None,
    include_done: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> List[RoutingJobOut]:
    rows = routing_crud.get_jobs_by_user(
        db,
        current_user.id,
        limit=limit,
        status=status,
        include_done=include_done,
    )
    return [_job_to_out(job, event) for job, event in rows]


@router.post("/routing/jobs/{job_id}/retry", response_model=RoutingJobOut)
async def retry_routing_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> RoutingJobOut:
    job, event = routing_crud.get_job_by_user(db, current_user.id, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Routing job not found")
    if job.status == "processing":
        raise HTTPException(
            status_code=409, detail="Routing job is currently processing"
        )
    job, event = routing_crud.retry_job(db, job, event=event)
    return _job_to_out(job, event)


@router.post("/routing/simulate", response_model=RoutingSimulationResponse)
async def simulate_routing(
    simulation: RoutingSimulationRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> RoutingSimulationResponse:
    message_text = (simulation.message_text or "").strip()
    connector_id = simulation.connector_id
    connector_type = simulation.connector_type
    if connector_id:
        connector = (
            db.query(models.Connector)
            .filter(models.Connector.id == connector_id)
            .first()
        )
        if not connector or connector.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Connector not found")
        connector_type = connector.connector_type

    signal_class = (simulation.signal_class or "").strip().lower() or None
    passive_source = (simulation.passive_source or "").strip().lower() or None
    if (
        not signal_class
        and connector_type
        and connector_type
        in {"snmp", "arp", "ais_safety_text", "aprs", "acars", "ax25", "cap"}
    ):
        signal_class = "passive"
        passive_source = passive_source or connector_type

    rules = (
        db.query(models.RoutingRule)
        .filter(models.RoutingRule.user_id == current_user.id)
        .order_by(models.RoutingRule.priority.desc(), models.RoutingRule.id.asc())
        .all()
    )
    bots = {
        bot.id: bot
        for bot in (
            db.query(models.Bot).filter(models.Bot.user_id == current_user.id).all()
        )
    }

    matches: list[RoutingSimulationMatch] = []
    for rule in rules:
        if rule.connector_id and connector_id and rule.connector_id != connector_id:
            continue
        if rule.connector_id and connector_id is None:
            continue
        if (
            rule.connector_type
            and connector_type
            and rule.connector_type != connector_type
        ):
            continue
        if rule.connector_type and connector_type is None:
            continue
        if not _rule_matches_text(
            message_text,
            rule.match_type,
            rule.match_value,
            connector_type=connector_type,
            signal_class=signal_class,
            passive_source=passive_source,
        ):
            continue
        bot = bots.get(rule.bot_id)
        matches.append(
            RoutingSimulationMatch(
                rule_id=rule.id,
                rule_name=rule.name,
                bot_id=rule.bot_id,
                bot_name=bot.name if bot else None,
                priority=rule.priority,
                match_type=rule.match_type,
                match_value=rule.match_value,
                is_active=bool(rule.is_active),
            )
        )

    active_matches = [match for match in matches if bool(match.is_active)]

    if active_matches:
        selected = active_matches[0]
        selected_rule_model = next(
            (rule for rule in rules if rule.id == selected.rule_id), None
        )
        return RoutingSimulationResponse(
            selected_rule_id=selected.rule_id,
            selected_bot_id=selected.bot_id,
            selected_bot_name=selected.bot_name,
            selected_destination_connector_id=(
                selected_rule_model.destination_connector_id
                if selected_rule_model
                else None
            ),
            decision="matched_rule",
            matches=matches,
        )

    if matches:
        return RoutingSimulationResponse(
            selected_rule_id=None,
            selected_bot_id=None,
            selected_bot_name=None,
            selected_destination_connector_id=None,
            decision="shadow_match",
            matches=matches,
        )

    fallback = (
        db.query(models.Bot)
        .filter(models.Bot.user_id == current_user.id)
        .order_by(models.Bot.id.asc())
        .all()
    )
    welcome = next((bot for bot in fallback if bot.name == "Welcome Bot"), None)
    selected_bot = welcome or (fallback[0] if fallback else None)
    if selected_bot:
        return RoutingSimulationResponse(
            selected_rule_id=None,
            selected_bot_id=selected_bot.id,
            selected_bot_name=selected_bot.name,
            selected_destination_connector_id=None,
            decision="fallback_bot",
            matches=[],
        )
    return RoutingSimulationResponse(
        selected_destination_connector_id=None,
        decision="no_bot",
        matches=[],
    )
