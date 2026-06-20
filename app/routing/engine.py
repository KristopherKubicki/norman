from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app import models
from app.core.logging import setup_logger
from app.core.command_policy import evaluate_tmux_payload
from app.core.config import get_settings
from app.core.safety_controls import (
    effective_read_only,
    routing_actions_block_reason,
)
from app.core.hooks import run_pre_hooks, run_post_hooks
from app.crud.bot import get_bots_by_user_id, get_bot_by_id
from app.crud.message import create_message, get_last_messages_by_bot_id
from app.crud.interaction import create_interaction
from app.crud import routing as routing_crud
from app.crud import command_approval as command_approval_crud
from app.schemas.interaction import InteractionCreate
from app.handlers.openai_handler import create_chat_interaction
from app.core.exceptions import APIError
from app.connectors.webhook_connector import WebhookConnector
from app.connectors.connector_utils import get_connector
from app.routing.circuit_breaker import CircuitOpen, connector_circuit_breaker

logger = setup_logger(__name__)


async def _notify_approval_created(approval, connector_name: str) -> None:
    # Best-effort webhook notification for operator approvals.
    try:
        from app.services.notifications import approval_payload, maybe_notify_webhook

        await maybe_notify_webhook(
            event_type="approval.created",
            payload=approval_payload(approval=approval, connector_name=connector_name),
        )
    except Exception:
        return


class DeliveryFailed(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


PASSIVE_CONNECTOR_TYPES = {
    "snmp",
    "arp",
    "ais_safety_text",
    "aprs",
    "acars",
    "ax25",
    "cap",
    "home_assistant",
    "unifi",
    "pfsense_opnsense",
    "proxmox",
    "docker_events",
    "prometheus_alertmanager",
    "ntfy",
    "pushover",
    "frigate",
    "hubitat",
    "glimpser",
    "activity_monitor",
}


def _idempotency_key(connector_id: Optional[int], payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    base = f"{connector_id}:{raw}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _extract_text(normalized: Optional[Dict[str, Any]], payload: Any) -> str:
    for source in (normalized, payload if isinstance(payload, dict) else None):
        if not source:
            continue
        for key in ("text", "message", "content", "body"):
            value = source.get(key) if isinstance(source, dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(payload, str) and payload.strip():
        return payload.strip()
    return ""


def _extract_signal_context(
    normalized: Optional[Dict[str, Any]],
    payload: Any,
    connector_type: Optional[str],
) -> Dict[str, Optional[str]]:
    context: Dict[str, Optional[str]] = {
        "signal_class": None,
        "passive_source": None,
        "provenance": None,
    }

    for source in (normalized, payload if isinstance(payload, dict) else None):
        if not isinstance(source, dict):
            continue
        for key in ("signal_class", "note_class", "class"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                context["signal_class"] = value.strip().lower()
                break
        for key in ("passive_source", "sensor_type", "source_type", "sensor"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                context["passive_source"] = value.strip().lower()
                break

        trusted_flag = source.get("trusted")
        if isinstance(trusted_flag, bool):
            context["provenance"] = "trusted" if trusted_flag else "untrusted"

        for key in ("provenance", "trust", "trust_level", "source_trust"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                trust_value = value.strip().lower()
                if trust_value in {"trusted", "verified", "internal"}:
                    context["provenance"] = "trusted"
                elif trust_value in {"untrusted", "external", "spoofed"}:
                    context["provenance"] = "untrusted"
                elif trust_value in {"unknown"}:
                    context["provenance"] = "unknown"
                break

    connector_type_norm = (connector_type or "").strip().lower()
    if connector_type_norm in PASSIVE_CONNECTOR_TYPES:
        context["signal_class"] = context["signal_class"] or "passive"
        context["passive_source"] = context["passive_source"] or connector_type_norm

    context["provenance"] = context["provenance"] or "unknown"

    return context


def _build_routing_text(text: str, context: Dict[str, Optional[str]]) -> str:
    signal_class = context.get("signal_class")
    passive_source = context.get("passive_source")
    provenance = (context.get("provenance") or "").strip().lower()
    tags = []
    if signal_class:
        tags.append(signal_class)
    if passive_source:
        tags.append(f"{signal_class or 'signal'}:{passive_source}")
    if provenance and provenance != "trusted":
        tags.append(f"trust:{provenance}")
    if not tags:
        return text
    prefix = " ".join(f"[{tag}]" for tag in tags)
    return f"{prefix} {text}".strip()


def _match_rule(
    text: str,
    rule: models.RoutingRule,
    signal_context: Optional[Dict[str, Optional[str]]] = None,
) -> bool:
    if rule.match_type == "all":
        return True

    signal_context = signal_context or {}
    signal_class = (signal_context.get("signal_class") or "").strip().lower()
    passive_source = (signal_context.get("passive_source") or "").strip().lower()

    if rule.match_type == "passive":
        if signal_class != "passive":
            return False
        if not rule.match_value:
            return True
        needle = rule.match_value.strip().lower()
        if not needle:
            return True
        return needle in {passive_source, signal_class}

    if not text:
        return False
    if rule.match_type == "contains":
        return rule.match_value.lower() in text.lower() if rule.match_value else False
    if rule.match_type == "regex":
        if not rule.match_value:
            return False
        return re.search(rule.match_value, text) is not None
    return False


def _select_rule(
    db: Session,
    *,
    user_id: int,
    connector_id: Optional[int],
    connector_type: Optional[str],
    text: str,
    signal_context: Optional[Dict[str, Optional[str]]] = None,
) -> Optional[models.RoutingRule]:
    rules = (
        db.query(models.RoutingRule)
        .filter(models.RoutingRule.user_id == user_id)
        .filter(models.RoutingRule.is_active.is_(True))
        .order_by(models.RoutingRule.priority.desc(), models.RoutingRule.id.asc())
        .all()
    )
    for rule in rules:
        if rule.connector_id and connector_id != rule.connector_id:
            continue
        if rule.connector_type and connector_type != rule.connector_type:
            continue
        if _match_rule(text, rule, signal_context=signal_context):
            return rule
    return None


def _normalize_payload(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        return {"raw": payload}
    return {"raw": json.dumps(payload, default=str)}


def _normalize_dict(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(data, dict):
        return data
    return {}


def _reply_address(
    normalized: Dict[str, Any], payload: Any, *keys: str
) -> Optional[str]:
    sources = [normalized]
    if isinstance(payload, dict):
        sources.append(payload)
    for key in keys:
        for source in sources:
            value = source.get(key) if isinstance(source, dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _connector_policy(connector: models.Connector) -> Dict[str, Any]:
    cfg = connector.config if isinstance(connector.config, dict) else {}
    policy = cfg.get("policy") if isinstance(cfg.get("policy"), dict) else {}
    return policy


def _int_or_default(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _consume_delivery_budget(
    *,
    connector_id: int,
    per_minute: int,
    per_hour: int,
) -> Tuple[bool, str]:
    if per_minute <= 0 and per_hour <= 0:
        return True, ""

    now = time.time()
    bucket = getattr(process_routing_job, "_delivery_budget", {})
    state = bucket.get(int(connector_id), {})
    minute_stamps = [ts for ts in state.get("m", []) if now - ts < 60.0]
    hour_stamps = [ts for ts in state.get("h", []) if now - ts < 3600.0]

    if per_minute > 0 and len(minute_stamps) >= per_minute:
        return False, "per-minute budget exceeded"
    if per_hour > 0 and len(hour_stamps) >= per_hour:
        return False, "per-hour budget exceeded"

    minute_stamps.append(now)
    hour_stamps.append(now)
    bucket[int(connector_id)] = {"m": minute_stamps, "h": hour_stamps}
    setattr(process_routing_job, "_delivery_budget", bucket)
    return True, ""


async def _generate_bot_reply(
    *,
    db: Session,
    bot_id: int,
    user_text: str,
    history_limit: int = 10,
) -> Optional[str]:
    user_text, hook_ctx = await run_pre_hooks(user_text, {"bot_id": bot_id})
    message = create_message(db=db, bot_id=bot_id, text=user_text, source="user")

    last_messages = get_last_messages_by_bot_id(
        db=db, bot_id=bot_id, limit=history_limit
    )
    bot = get_bot_by_id(db=db, bot_id=bot_id)
    if not bot:
        return None

    messages = [{"role": "system", "content": bot.system_prompt}]
    for msg in reversed(last_messages):
        messages.append({"role": msg.source, "content": msg.text})

    def token_count(msgs):
        return sum(len(m["content"].split()) for m in msgs)

    while token_count(messages) > bot.default_prompt_tokens and len(messages) > 1:
        messages.pop(1)

    try:
        interaction_response = await create_chat_interaction(
            model=bot.gpt_model,
            messages=messages,
            max_tokens=bot.default_response_tokens,
        )
    except APIError as exc:
        logger.error("OpenAI interaction failed: %s", exc)
        return None

    assistant_text = interaction_response["choices"][0]["message"]["content"]
    assistant_text, hook_ctx = await run_post_hooks(assistant_text, hook_ctx)

    interaction_in = InteractionCreate(
        bot_id=bot_id,
        message_id=message.id,
        input_data=message.text,
        gpt_model=interaction_response["model"],
        output_data=assistant_text,
        tokens_in=interaction_response["usage"]["prompt_tokens"],
        tokens_out=interaction_response.get("usage", {}).get("completion_tokens", 0),
        status_code=200,
    )
    create_interaction(db=db, interaction=interaction_in)
    create_message(db=db, bot_id=bot_id, text=assistant_text, source="assistant")
    return assistant_text


async def enqueue_routing_job(
    *,
    db: Session,
    connector: models.Connector,
    normalized: Optional[Dict[str, Any]],
    payload: Any,
    max_attempts: int = 5,
    defer_until: Optional[datetime] = None,
) -> Dict[str, Any]:
    raw_text = _extract_text(normalized, payload)
    signal_context = _extract_signal_context(
        normalized, payload, connector.connector_type
    )
    text = _build_routing_text(raw_text, signal_context)
    idempotency = _idempotency_key(connector.id, payload)

    existing = (
        db.query(models.RoutingEvent)
        .filter(models.RoutingEvent.idempotency_key == idempotency)
        .first()
    )
    if existing:
        return {"status": "duplicate", "event_id": existing.id}

    event = models.RoutingEvent(
        user_id=connector.user_id,
        connector_id=connector.id,
        connector_type=connector.connector_type,
        message_text=text,
        payload=_normalize_payload(payload),
        status="queued",
        delivery_status="queued",
        idempotency_key=idempotency,
    )
    routing_crud.create_event(db, event)

    settings = get_settings()
    action_hold_reason = routing_actions_block_reason(settings)
    if action_hold_reason:
        event.status = "logged"
        event.delivery_status = "disabled"
        event.delivery_error = action_hold_reason
        routing_crud.update_event(db, event)
        return {"status": "logged", "event_id": event.id}

    if getattr(settings, "routing_ingest_only", False):
        # Log-only mode: persist the event, but do not create a routing job.
        event.status = "logged"
        event.delivery_status = "disabled"
        routing_crud.update_event(db, event)
        return {"status": "logged", "event_id": event.id}

    normalized_payload = _normalize_dict(normalized)
    normalized_payload.setdefault("signal_class", signal_context.get("signal_class"))
    normalized_payload.setdefault(
        "passive_source", signal_context.get("passive_source")
    )
    normalized_payload.setdefault("provenance", signal_context.get("provenance"))

    job = models.RoutingJob(
        event_id=event.id,
        connector_id=connector.id,
        status="pending",
        attempts=0,
        max_attempts=max_attempts,
        next_attempt_at=defer_until or datetime.utcnow(),
        payload=_normalize_payload(payload),
        normalized=normalized_payload,
    )
    routing_crud.create_job(db, job)
    return {"status": "queued", "event_id": event.id}


async def process_routing_job(
    *,
    db: Session,
    job: models.RoutingJob,
) -> Tuple[str, Optional[int]]:
    event = routing_crud.get_event(db, job.event_id) if job.event_id else None
    connector = (
        db.query(models.Connector)
        .filter(models.Connector.id == job.connector_id)
        .first()
    )
    payload = job.payload or {}
    normalized = job.normalized or {}
    raw_text = _extract_text(normalized, payload)
    signal_context = _extract_signal_context(
        normalized, payload, connector.connector_type
    )
    text = _build_routing_text(raw_text, signal_context)

    if not event or not connector:
        job.status = "dead"
        job.last_error = "Missing event or connector"
        routing_crud.update_job(db, job)
        return ("dead", None)

    connector.last_message_received = datetime.utcnow()
    event.status = "received"
    routing_crud.update_event(db, event)

    if not text:
        event.status = "ignored"
        routing_crud.update_event(db, event)
        return ("ignored", event.id)

    rule = _select_rule(
        db,
        user_id=connector.user_id,
        connector_id=connector.id,
        connector_type=connector.connector_type,
        text=text,
        signal_context=signal_context,
    )

    bot_id: Optional[int] = None
    if rule:
        bot_id = rule.bot_id
        event.rule_id = rule.id
    else:
        if signal_context.get("signal_class") == "passive":
            event.status = "received"
            event.delivery_status = "disabled"
            event.delivery_error = "passive signal stored; no routing rule"
            routing_crud.update_event(db, event)
            return (event.status, event.id)
        bots = get_bots_by_user_id(db, connector.user_id)
        welcome = next((bot for bot in bots if bot.name == "Welcome Bot"), None)
        bot_id = (welcome or bots[0]).id if bots else None

    if not bot_id:
        event.status = "dropped"
        event.error = "No bot available for routing"
        routing_crud.update_event(db, event)
        return ("dropped", event.id)

    event.bot_id = bot_id
    app_settings = get_settings()
    action_hold_reason = routing_actions_block_reason(app_settings)
    if action_hold_reason:
        event.status = "routed"
        event.delivery_status = "disabled"
        event.delivery_error = action_hold_reason
        routing_crud.update_event(db, event)
        return (event.status, event.id)

    if (
        bool(getattr(app_settings, "safety_provenance_enforce", False))
        and (signal_context.get("provenance") or "").strip().lower() == "untrusted"
    ):
        event.status = "routed"
        event.delivery_status = "blocked_provenance"
        event.delivery_error = "untrusted signal provenance"
        routing_crud.update_event(db, event)
        return (event.status, event.id)

    assistant_text = await _generate_bot_reply(db=db, bot_id=bot_id, user_text=text)
    if assistant_text is None:
        event.status = "failed"
        event.error = "Bot response failed"
        routing_crud.update_event(db, event)
        return ("failed", event.id)

    event.status = "routed"

    delivery_connector = connector
    if rule and getattr(rule, "destination_connector_id", None):
        dest = (
            db.query(models.Connector)
            .filter(models.Connector.id == rule.destination_connector_id)
            .first()
        )
        if not dest or dest.user_id != connector.user_id:
            event.delivery_status = "failed"
            event.delivery_error = "Destination connector not found"
            routing_crud.update_event(db, event)
            raise DeliveryFailed("Destination connector not found")
        delivery_connector = dest

    if (
        rule
        and getattr(rule, "destination_connector_id", None)
        and int(delivery_connector.id or 0) == int(connector.id or 0)
    ):
        event.delivery_status = "blocked"
        event.delivery_error = "self-route blocked"
        routing_crud.update_event(db, event)
        return (event.status, event.id)

    event.destination_connector_id = (
        int(delivery_connector.id)
        if delivery_connector and delivery_connector.id
        else None
    )
    event.destination_connector_type = (
        delivery_connector.connector_type if delivery_connector else None
    )

    policy = _connector_policy(delivery_connector)
    per_minute = _int_or_default(
        policy.get("budget_per_minute"),
        _int_or_default(
            getattr(app_settings, "safety_budget_default_per_minute", 0), 0
        ),
    )
    # Backward-compatible alias used by earlier tmux policy versions.
    if per_minute <= 0:
        per_minute = _int_or_default(policy.get("rate_limit_per_min"), 0)
    per_hour = _int_or_default(
        policy.get("budget_per_hour"),
        _int_or_default(getattr(app_settings, "safety_budget_default_per_hour", 0), 0),
    )
    allowed, budget_reason = _consume_delivery_budget(
        connector_id=int(delivery_connector.id),
        per_minute=max(0, per_minute),
        per_hour=max(0, per_hour),
    )
    if not allowed:
        event.delivery_status = "blocked_budget"
        event.delivery_error = budget_reason
        if (
            bool(getattr(app_settings, "safety_budget_autolock", True))
            and delivery_connector.connector_type == "tmux"
        ):
            cfg = dict(delivery_connector.config or {})
            if not bool(cfg.get("locked")):
                cfg["locked"] = True
                cfg["locked_reason"] = f"budget:{budget_reason}"
                delivery_connector.config = cfg
                db.add(delivery_connector)
                db.commit()
                db.refresh(delivery_connector)
        routing_crud.update_event(db, event)
        return (event.status, event.id)

    reply_webhook_url = None
    if delivery_connector.config:
        reply_webhook_url = delivery_connector.config.get("reply_webhook_url")

    # Circuit breaker: if the connector is repeatedly failing, pause delivery
    # attempts for a short window. Jobs will be rescheduled without burning
    # attempt counters.
    if connector_circuit_breaker.is_open(delivery_connector.id):
        until = connector_circuit_breaker.opened_until(delivery_connector.id)
        event.delivery_status = "circuit_open"
        event.delivery_error = (
            connector_circuit_breaker.state(delivery_connector.id).last_error
            or "circuit_open"
        )
        routing_crud.update_event(db, event)
        raise CircuitOpen(
            delivery_connector.id, until, event.delivery_error or "circuit_open"
        )

    delivery_ok = False
    # Safety gate: execution-capable connectors (tmux, etc.) must pass deterministic policy.
    if delivery_connector.connector_type == "tmux":
        mode = app_settings.safety_default_tmux_mode or "chat"
        allow_meta = False
        connector_cfg = (
            dict(delivery_connector.config or {})
            if isinstance(delivery_connector.config, dict)
            else {}
        )
        if connector_cfg:
            mode = connector_cfg.get("mode") or policy.get("mode") or mode
            allow_meta = bool(
                connector_cfg.get(
                    "allow_shell_metachar",
                    policy.get("allow_shell_metachar", False),
                )
            )
        if bool(connector_cfg.get("locked")):
            event.delivery_status = "blocked"
            event.delivery_error = "Session is locked by failsafe policy"
            routing_crud.update_event(db, event)
            return (event.status, event.id)

        operator_mode = (
            str(connector_cfg.get("operator_mode") or "")
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )
        if operator_mode == "take":
            note = str(connector_cfg.get("operator_note") or "").strip()
            event.delivery_status = "blocked_operator_takeover"
            event.delivery_error = note or "Session is under operator takeover"
            routing_crud.update_event(db, event)
            return (event.status, event.id)

        # Global kill switch / read-only: never execute from routing worker.
        if (not getattr(app_settings, "safety_execution_enabled", True)) or (
            effective_read_only(app_settings)
        ):
            approval = command_approval_crud.create(
                db,
                user_id=connector.user_id,
                connector_id=int(delivery_connector.id),
                event_id=int(event.id) if event and event.id else None,
                command_text=raw_text,
                command_class="change",
                reason="execution disabled"
                if not getattr(app_settings, "safety_execution_enabled", True)
                else "read-only mode",
            )
            await _notify_approval_created(
                approval, connector_name=delivery_connector.name or ""
            )
            event.delivery_status = "needs_approval"
            event.delivery_error = f"approval_id={approval.id}"
            routing_crud.update_event(db, event)
            return (event.status, event.id)

        # Execute the *raw* operator command, not the assistant text.
        decision = evaluate_tmux_payload(
            raw_text, mode=mode, allow_shell_metachar=allow_meta, profile=policy
        )
        if decision.decision != "allow":
            event.delivery_status = (
                "needs_approval" if decision.decision == "needs_approval" else "blocked"
            )
            if decision.decision == "needs_approval":
                approval = command_approval_crud.create(
                    db,
                    user_id=connector.user_id,
                    connector_id=int(delivery_connector.id),
                    event_id=int(event.id) if event and event.id else None,
                    command_text=raw_text,
                    command_class=decision.command_class,
                    reason=decision.reason,
                    confirm_token=decision.confirm_token,
                )
                await _notify_approval_created(
                    approval, connector_name=delivery_connector.name or ""
                )
                token_note = (
                    f" confirm_token={approval.confirm_token}"
                    if approval.confirm_token
                    else ""
                )
                event.delivery_error = f"approval_id={approval.id}{token_note}"
            else:
                event.delivery_error = decision.reason
            routing_crud.update_event(db, event)
            return (event.status, event.id)
    delivery_error = ""

    if reply_webhook_url:
        try:
            sender = WebhookConnector(
                reply_webhook_url, config=delivery_connector.config
            )
            await sender.send_message(
                {
                    "text": assistant_text,
                    "bot_id": bot_id,
                    "event_id": event.id,
                    "source_connector_id": connector.id,
                    "source_connector_type": connector.connector_type,
                    "source_message_text": text,
                    "raw_text": raw_text,
                    "source_normalized": normalized,
                    "source_payload": payload,
                    "reply_to": _reply_address(
                        normalized,
                        payload,
                        "reply_to",
                        "from",
                        "From",
                    ),
                    "reply_from": _reply_address(
                        normalized,
                        payload,
                        "reply_from",
                        "to",
                        "To",
                    ),
                }
            )
            event.delivery_status = "sent"
            delivery_ok = True
        except Exception as exc:
            event.delivery_status = "failed"
            delivery_error = str(exc)
            event.delivery_error = delivery_error
    else:
        try:
            instance = get_connector(
                delivery_connector.connector_type, delivery_connector.config or {}
            )
            payload_to_send = (
                {"command": raw_text, "text": assistant_text, "bot_id": bot_id}
                if delivery_connector.connector_type == "tmux"
                else assistant_text
            )
            result = instance.send_message(payload_to_send)
            if isinstance(result, dict):
                result = result.get("result", result)
            if asyncio.iscoroutine(result):
                await result
            event.delivery_status = "sent"
            delivery_ok = True
        except TypeError:
            try:
                instance = get_connector(
                    delivery_connector.connector_type, delivery_connector.config or {}
                )
                payload_to_send = (
                    {"command": raw_text, "text": assistant_text, "bot_id": bot_id}
                    if delivery_connector.connector_type == "tmux"
                    else {"text": assistant_text, "bot_id": bot_id}
                )
                result = instance.send_message(payload_to_send)
                if asyncio.iscoroutine(result):
                    await result
                event.delivery_status = "sent"
                delivery_ok = True
            except Exception as exc:
                event.delivery_status = "failed"
                delivery_error = str(exc)
                event.delivery_error = delivery_error
        except Exception as exc:
            event.delivery_status = "failed"
            delivery_error = str(exc)
            event.delivery_error = delivery_error

    if delivery_ok:
        connector_circuit_breaker.record_success(delivery_connector.id)
        delivery_connector.last_message_sent = datetime.utcnow()
        # best-effort update
        try:
            db.commit()
        except Exception:
            db.rollback()
        routing_crud.update_event(db, event)
        return (event.status, event.id)

    # Delivery failed: record circuit breaker state, persist event error, and
    # raise so the worker retries / dead-letters the job.
    connector_circuit_breaker.record_failure(
        delivery_connector.id, delivery_error or "delivery_failed"
    )
    event.delivery_status = "failed"
    if delivery_error and not event.delivery_error:
        event.delivery_error = delivery_error
    routing_crud.update_event(db, event)
    raise DeliveryFailed(event.delivery_error or delivery_error or "delivery_failed")

    routing_crud.update_event(db, event)
    return (event.status, event.id)


def compute_retry_delay(attempts: int) -> timedelta:
    return timedelta(seconds=min(60, 2**attempts))
