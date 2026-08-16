#!/usr/bin/env python3
"""Durable admission checks for Norman Codex console sessions."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


MODEL_REGISTRY_ENV = "NORMAN_MODEL_ROLE_CONFIG"
LEGACY_MODEL_REGISTRY_ENV = "NORMAN_NORLLAMA_MODEL_ROLE_CONFIG"
LOCAL_MODEL_REGISTRY_PATH = Path(__file__).with_name("model_roles.json")
REPO_MODEL_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "norllama" / "model_roles.json"
)
ROLE_ORDER = ("resident", "economy", "authority", "frontier")


@lru_cache(maxsize=4)
def _load_model_registry_file(path: str) -> dict[str, Any]:
    registry_path = Path(path)
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "norman.norllama.model-roles.v1"
        or not isinstance(payload.get("roles"), dict)
    ):
        return {}
    return payload


def _load_model_registry(path: str = "") -> dict[str, Any]:
    registry_path = Path(
        path
        or os.getenv(MODEL_REGISTRY_ENV)
        or os.getenv(LEGACY_MODEL_REGISTRY_ENV)
        or (
            LOCAL_MODEL_REGISTRY_PATH
            if LOCAL_MODEL_REGISTRY_PATH.exists()
            else REPO_MODEL_REGISTRY_PATH
        )
    )
    return _load_model_registry_file(str(registry_path.resolve()))


def _model_row(model: str) -> dict[str, Any]:
    requested = str(model or "").strip().lower()
    registry = _load_model_registry()
    roles = registry.get("roles")
    if isinstance(roles, dict):
        for role in ROLE_ORDER:
            raw = roles.get(role)
            row = raw if isinstance(raw, dict) else {}
            identifiers = {
                str(row.get("model") or "").strip().lower(),
                *{
                    str(alias or "").strip().lower()
                    for alias in row.get("aliases") or []
                },
            }
            if requested in identifiers:
                return row
    models = registry.get("models")
    if isinstance(models, dict):
        for model_id, raw in models.items():
            row = raw if isinstance(raw, dict) else {}
            identifiers = {
                str(model_id or "").strip().lower(),
                *{
                    str(alias or "").strip().lower()
                    for alias in row.get("aliases") or []
                },
            }
            if requested in identifiers:
                return {"model": str(model_id), **row}
    return {}


def model_capability(model: str, name: str, default: Any = None) -> Any:
    capabilities = _model_row(model).get("capabilities")
    if not isinstance(capabilities, dict):
        return default
    return capabilities.get(name, default)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name, "")
    if not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


def normalize_reasoning_effort(value: Any, default: str = "high") -> str:
    clean = str(value or "").strip().lower().replace("_", "").replace("-", "")
    aliases = {
        "low": "low",
        "medium": "medium",
        "med": "medium",
        "high": "high",
        "xhigh": "xhigh",
    }
    return aliases.get(clean, default)


def model_requires_named_escalation(value: Any) -> bool:
    return bool(
        model_capability(str(value or ""), "named_escalation_required", False)
    )


def is_context_checkpoint_prompt(value: Any) -> bool:
    prompt = " ".join(str(value or "").lower().split())
    if not prompt:
        return False
    markers = (
        "/compact",
        "compact this thread",
        "compact the thread",
        "compact our work",
        "save/compact",
        "save compact",
        "context save",
        "save this thread",
        "save the thread",
        "handoff summary",
        "create a handoff",
        "prepare a handoff",
        "fresh-thread handoff",
        "fresh thread handoff",
    )
    return any(marker in prompt for marker in markers)


@dataclass(frozen=True)
class SessionBudgetPolicy:
    enabled: bool
    checkpoint_tokens: int
    reauthorization_tokens: int
    max_age_seconds: int
    max_tool_calls: int
    require_named_escalation: bool


def policy_from_env() -> SessionBudgetPolicy:
    checkpoint_tokens = _env_int(
        "NORMAN_CODEX_SESSION_CHECKPOINT_TOKENS", 160_000, minimum=1
    )
    reauthorization_tokens = max(
        checkpoint_tokens,
        _env_int(
            "NORMAN_CODEX_SESSION_REAUTHORIZATION_TOKENS",
            200_000,
            minimum=checkpoint_tokens,
        ),
    )
    return SessionBudgetPolicy(
        enabled=_env_bool("NORMAN_CODEX_SESSION_BUDGET_ENABLED", True),
        checkpoint_tokens=checkpoint_tokens,
        reauthorization_tokens=reauthorization_tokens,
        max_age_seconds=_env_int(
            "NORMAN_CODEX_SESSION_MAX_AGE_SECONDS", 24 * 60 * 60, minimum=60
        ),
        max_tool_calls=_env_int(
            "NORMAN_CODEX_SESSION_MAX_TOOL_CALLS", 1_000, minimum=1
        ),
        require_named_escalation=_env_bool(
            "NORMAN_CODEX_REQUIRE_NAMED_ESCALATION", True
        ),
    )


def empty_session_usage(
    thread_id: str = "", observed_at: int | None = None
) -> dict[str, Any]:
    return {
        "thread_id": str(thread_id or "").strip(),
        "first_started_at": 0,
        "last_finished_at": 0,
        "age_seconds": 0,
        "total_tokens": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "tool_calls": 0,
        "turn_count": 0,
        "observed_at": int(observed_at or time.time()),
    }


def session_usage(
    state_db_path: Path | str,
    thread_id: str,
    *,
    observed_at: int | None = None,
) -> dict[str, Any]:
    observed = int(observed_at or time.time())
    clean_thread_id = str(thread_id or "").strip()
    usage = empty_session_usage(clean_thread_id, observed)
    if not clean_thread_id:
        return usage

    path = Path(state_db_path)
    if not path.exists():
        return usage
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
        rows = conn.execute(
            """
            SELECT started_at, finished_at, input_tokens, cached_input_tokens,
                   output_tokens, total_tokens, payload_json
            FROM usage_events
            WHERE thread_id = ?
            ORDER BY started_at ASC, id ASC
            """,
            (clean_thread_id,),
        ).fetchall()
    except sqlite3.Error:
        return usage
    finally:
        try:
            conn.close()
        except Exception:
            pass

    for row in rows:
        started_at = int(row[0] or 0)
        finished_at = int(row[1] or 0)
        usage["first_started_at"] = (
            started_at
            if not usage["first_started_at"]
            else min(usage["first_started_at"], started_at or usage["first_started_at"])
        )
        usage["last_finished_at"] = max(usage["last_finished_at"], finished_at)
        usage["input_tokens"] += int(row[2] or 0)
        usage["cached_input_tokens"] += int(row[3] or 0)
        usage["output_tokens"] += int(row[4] or 0)
        usage["total_tokens"] += int(row[5] or 0)
        usage["turn_count"] += 1
        try:
            payload = json.loads(str(row[6] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        usage["tool_calls"] += max(
            0,
            int(
                payload.get("broker_tool_calls")
                or payload.get("tool_call_count")
                or payload.get("actual_tool_calls")
                or 0
            ),
        )

    if usage["first_started_at"]:
        usage["age_seconds"] = max(0, observed - usage["first_started_at"])
    return usage


def evaluate_admission(
    policy: SessionBudgetPolicy,
    *,
    state_db_path: Path | str,
    state_db_enabled: bool,
    thread_id: str,
    model: str,
    reasoning_effort: str,
    escalation_reason: str = "",
    reauthorization_reason: str = "",
    checkpoint_intent: bool = False,
    observed_at: int | None = None,
) -> dict[str, Any]:
    observed = int(observed_at or time.time())
    effort = normalize_reasoning_effort(reasoning_effort)
    reason = " ".join(str(escalation_reason or "").split())[:360]
    reauthorization = " ".join(str(reauthorization_reason or "").split())[:360]
    usage = (
        session_usage(state_db_path, thread_id, observed_at=observed)
        if state_db_enabled
        else empty_session_usage(thread_id, observed)
    )
    decision = {
        "schema": "norman.tui.session-admission.v1",
        "observed_at": observed,
        "policy": asdict(policy),
        "usage": usage,
        "thread_id": str(thread_id or "").strip(),
        "model": str(model or "").strip(),
        "reasoning_effort": effort,
        "escalation_reason": reason,
        "reauthorization_reason": reauthorization,
        "checkpoint_intent": bool(checkpoint_intent),
        "allowed": True,
        "action": "allow",
        "reason_code": "within_budget",
        "reason": "Session is within its configured budget.",
    }
    if not policy.enabled:
        decision.update(
            {
                "action": "disabled",
                "reason_code": "policy_disabled",
                "reason": "Session budget enforcement is disabled for this console.",
            }
        )
        return decision

    requires_escalation = effort == "xhigh" or model_requires_named_escalation(model)
    if policy.require_named_escalation and requires_escalation and len(reason) < 12:
        decision.update(
            {
                "allowed": False,
                "action": "deny",
                "reason_code": "named_escalation_required",
                "reason": (
                    "GPT-5.5 and xhigh requests require a named escalation reason "
                    "before work is admitted."
                ),
            }
        )
        return decision

    hard_limit_hit = usage["total_tokens"] >= policy.reauthorization_tokens
    if hard_limit_hit and not checkpoint_intent and len(reauthorization) < 12:
        decision.update(
            {
                "allowed": False,
                "action": "deny",
                "reason_code": "reauthorization_required",
                "reason": (
                    "This thread exceeded its reauthorization token limit. Start a "
                    "fresh thread or provide a named reauthorization reason."
                ),
            }
        )
        return decision

    checkpoint_reasons: list[str] = []
    if usage["total_tokens"] >= policy.checkpoint_tokens:
        checkpoint_reasons.append("token_limit")
    if usage["age_seconds"] >= policy.max_age_seconds:
        checkpoint_reasons.append("age_limit")
    if usage["tool_calls"] >= policy.max_tool_calls:
        checkpoint_reasons.append("tool_call_limit")

    if checkpoint_reasons and not checkpoint_intent:
        decision.update(
            {
                "allowed": False,
                "action": "deny",
                "reason_code": "checkpoint_required",
                "checkpoint_reasons": checkpoint_reasons,
                "reason": (
                    "This thread reached a checkpoint limit. Save a compact handoff "
                    "and start a fresh thread before admitting more work."
                ),
            }
        )
        return decision

    if checkpoint_reasons:
        decision.update(
            {
                "action": "checkpoint",
                "reason_code": "checkpoint_admitted",
                "checkpoint_reasons": checkpoint_reasons,
                "reason": (
                    "A compact handoff is admitted once. The completed handoff will "
                    "start the next request in a fresh thread."
                ),
            }
        )
    elif hard_limit_hit:
        decision.update(
            {
                "action": "reauthorized",
                "reason_code": "reauthorized",
                "reason": "Operator reauthorization admitted this over-limit request.",
            }
        )
    elif requires_escalation:
        decision.update(
            {
                "action": "escalated",
                "reason_code": "named_escalation",
                "reason": "Named escalation admitted the requested model effort.",
            }
        )
    return decision
