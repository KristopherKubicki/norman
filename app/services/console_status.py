from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from fastapi import HTTPException

BILLING_URL = "https://platform.openai.com/settings/organization/billing/overview"
LIMITS_URL = "https://platform.openai.com/settings/organization/limits"
DEFAULT_USAGE_WINDOW_SECONDS = 24 * 60 * 60
DEFAULT_AUDIT_LIMIT = 200


@dataclass
class ConsoleCreditAssessment:
    issue_code: str = ""
    issue_label: str = ""
    issue_summary: str = ""
    billing_url: str = ""
    limits_url: str = ""
    recommended_speed: str = ""
    recommended_speed_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_web_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"http://{text}"
    parts = urlsplit(text)
    scheme = str(parts.scheme or "").strip().lower()
    if scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Web URL must use http or https.")
    if not str(parts.netloc or "").strip():
        raise HTTPException(status_code=400, detail="Web URL is missing a host.")
    return urlunsplit(
        (
            scheme,
            parts.netloc,
            parts.path or "",
            parts.query or "",
            parts.fragment or "",
        )
    )


def preview_console_text(value: str, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if not text or text in {"[no prompt yet]", "[no response yet]"}:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def console_auth_state(payload: dict[str, Any]) -> dict[str, Any]:
    auth = payload.get("auth")
    if not isinstance(auth, dict):
        return {
            "auth_required": False,
            "auth_mode": "",
            "auth_summary": "",
            "auth_verification_url": "",
            "auth_device_code": "",
        }
    return {
        "auth_required": bool(auth.get("required")),
        "auth_mode": str(auth.get("mode") or "").strip(),
        "auth_summary": str(auth.get("summary") or "").strip(),
        "auth_verification_url": str(auth.get("verification_url") or "").strip(),
        "auth_device_code": str(auth.get("device_code") or "").strip(),
    }


def _usage_summary_value(value: Any, key: str) -> int:
    if not isinstance(value, dict):
        return 0
    try:
        return int(value.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def console_usage_state(payload: dict[str, Any]) -> dict[str, Any]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return {
            "usage_tracked": False,
            "usage_window_seconds": DEFAULT_USAGE_WINDOW_SECONDS,
            "usage_turns": 0,
            "usage_successful_turns": 0,
            "usage_failed_turns": 0,
            "usage_input_tokens": 0,
            "usage_cached_input_tokens": 0,
            "usage_output_tokens": 0,
            "usage_total_tokens": 0,
            "usage_window_turns": 0,
            "usage_window_input_tokens": 0,
            "usage_window_cached_input_tokens": 0,
            "usage_window_output_tokens": 0,
            "usage_window_total_tokens": 0,
            "usage_last_turn_at": 0,
            "usage_last_turn_total_tokens": 0,
            "codex_subscription_capacity_state": "unknown",
            "codex_subscription_capacity_fresh": False,
            "codex_subscription_capacity_observed_at": 0,
            "codex_subscription_capacity_percent_left": -1,
            "codex_subscription_capacity_reset_hint": "",
            "codex_subscription_capacity_eligible": False,
            "codex_subscription_capacity_tokens_per_hour": 0,
            "codex_subscription_capacity_projected_tokens_to_reset": 0,
        }
    totals = usage.get("totals")
    window = usage.get("last_24h")
    last_turn = usage.get("last_turn")
    capacity = usage.get("codex_account_capacity")
    capacity = capacity if isinstance(capacity, dict) else {}
    forecast = capacity.get("forecast")
    forecast = forecast if isinstance(forecast, dict) else {}
    try:
        window_seconds = int(
            usage.get("window_seconds") or DEFAULT_USAGE_WINDOW_SECONDS
        )
    except (TypeError, ValueError):
        window_seconds = DEFAULT_USAGE_WINDOW_SECONDS
    return {
        "usage_tracked": bool(usage.get("tracked")),
        "usage_window_seconds": window_seconds,
        "usage_turns": _usage_summary_value(totals, "turns"),
        "usage_successful_turns": _usage_summary_value(totals, "successful_turns"),
        "usage_failed_turns": _usage_summary_value(totals, "failed_turns"),
        "usage_input_tokens": _usage_summary_value(totals, "input_tokens"),
        "usage_cached_input_tokens": _usage_summary_value(
            totals, "cached_input_tokens"
        ),
        "usage_output_tokens": _usage_summary_value(totals, "output_tokens"),
        "usage_total_tokens": _usage_summary_value(totals, "total_tokens"),
        "usage_window_turns": _usage_summary_value(window, "turns"),
        "usage_window_input_tokens": _usage_summary_value(window, "input_tokens"),
        "usage_window_cached_input_tokens": _usage_summary_value(
            window, "cached_input_tokens"
        ),
        "usage_window_output_tokens": _usage_summary_value(window, "output_tokens"),
        "usage_window_total_tokens": _usage_summary_value(window, "total_tokens"),
        "usage_last_turn_at": _usage_summary_value(last_turn, "finished_at"),
        "usage_last_turn_total_tokens": _usage_summary_value(last_turn, "total_tokens"),
        "codex_subscription_capacity_state": str(
            capacity.get("state") or "unknown"
        ).strip(),
        "codex_subscription_capacity_fresh": bool(capacity.get("fresh")),
        "codex_subscription_capacity_observed_at": _usage_summary_value(
            capacity, "observed_at"
        ),
        "codex_subscription_capacity_percent_left": (
            _usage_summary_value(capacity, "minimum_window_percent_left")
            if capacity.get("minimum_window_percent_left") is not None
            else -1
        ),
        "codex_subscription_capacity_reset_hint": str(
            capacity.get("reset_hint") or ""
        ).strip(),
        "codex_subscription_capacity_eligible": bool(
            capacity.get("eligible_for_subscription_route")
        ),
        "codex_subscription_capacity_tokens_per_hour": _usage_summary_value(
            forecast, "tokens_per_hour"
        ),
        "codex_subscription_capacity_projected_tokens_to_reset": _usage_summary_value(
            forecast, "projected_tokens_to_earliest_reset"
        ),
    }


def _console_request_token(query_items: dict[str, str], access_token: str = "") -> str:
    explicit = str(access_token or "").strip()
    if explicit:
        return explicit
    return str(query_items.get("token") or "").strip()


def console_status_url(web_url: str, *, access_token: str = "") -> str:
    normalized = str(web_url or "").strip()
    if not normalized:
        return ""
    try:
        parts = urlsplit(normalize_web_url(normalized))
    except HTTPException:
        return ""
    query_items = {
        key: value for key, value in parse_qsl(parts.query, keep_blank_values=True)
    }
    status_query = {}
    token = _console_request_token(query_items, access_token)
    if token:
        status_query["token"] = token
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            "/api/status",
            urlencode(status_query),
            "",
        )
    )


def console_audit_url(
    web_url: str,
    *,
    since_ts: int = 0,
    limit: int = DEFAULT_AUDIT_LIMIT,
    access_token: str = "",
) -> str:
    normalized = str(web_url or "").strip()
    if not normalized:
        return ""
    try:
        parts = urlsplit(normalize_web_url(normalized))
    except HTTPException:
        return ""
    query_items = {
        key: value for key, value in parse_qsl(parts.query, keep_blank_values=True)
    }
    audit_query: dict[str, str] = {}
    token = _console_request_token(query_items, access_token)
    if token:
        audit_query["token"] = token
    if since_ts > 0:
        audit_query["since"] = str(int(since_ts))
    if limit > 0:
        audit_query["limit"] = str(int(limit))
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            "/api/audit",
            urlencode(audit_query),
            "",
        )
    )


def fetch_console_status(
    web_url: str, *, access_token: str = "", timeout: float = 1.75
) -> dict[str, Any]:
    snapshot = {
        "reachable": False,
        "pending": False,
        "has_response": False,
        "status_message": "",
        "state": "",
        "last_action": "",
        "last_action_at": 0,
        "last_action_detail": "",
        "last_finished_at": 0,
        "prompt_preview": "",
        "response_preview": "",
        "last_error": "",
        "queue_depth": 0,
        "chat_model": "",
        "chat_reasoning_effort": "",
        "default_speed": "",
        "default_detail": 0,
        "auth_required": False,
        "auth_mode": "",
        "auth_summary": "",
        "auth_verification_url": "",
        "auth_device_code": "",
        **console_usage_state({}),
    }
    status_url = console_status_url(web_url, access_token=access_token)
    if not status_url:
        return snapshot
    request = Request(
        status_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "NormanPrime/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ):
        return snapshot
    if not isinstance(payload, dict):
        return snapshot

    last_prompt = str(payload.get("last_prompt") or "").strip()
    last_response = str(payload.get("last_response") or "").strip()
    has_response = bool(last_response and last_response != "[no response yet]")
    try:
        last_action_at = int(payload.get("last_action_at") or 0)
    except (TypeError, ValueError):
        last_action_at = 0
    try:
        last_finished_at = int(payload.get("last_finished_at") or 0)
    except (TypeError, ValueError):
        last_finished_at = 0
    try:
        queue_depth = int(payload.get("queue_depth") or 0)
    except (TypeError, ValueError):
        queue_depth = 0
    try:
        default_detail = int(payload.get("default_detail") or 0)
    except (TypeError, ValueError):
        default_detail = 0

    snapshot.update(
        {
            "reachable": True,
            "pending": bool(payload.get("pending")),
            "has_response": has_response,
            "status_message": str(payload.get("status_message") or "").strip(),
            "state": str(payload.get("state") or "").strip(),
            "last_action": str(payload.get("last_action") or "").strip(),
            "last_action_at": last_action_at,
            "last_action_detail": str(payload.get("last_action_detail") or "").strip(),
            "last_finished_at": last_finished_at,
            "prompt_preview": preview_console_text(last_prompt),
            "response_preview": preview_console_text(last_response),
            "last_error": str(payload.get("last_error") or "").strip(),
            "queue_depth": queue_depth,
            "chat_model": str(payload.get("chat_model") or "").strip(),
            "chat_reasoning_effort": str(
                payload.get("chat_reasoning_effort") or ""
            ).strip(),
            "default_speed": str(payload.get("default_speed") or "").strip().lower(),
            "default_detail": default_detail,
            **console_auth_state(payload),
            **console_usage_state(payload),
        }
    )
    return snapshot


async def fetch_console_status_map(web_urls: list[str]) -> dict[str, dict[str, Any]]:
    unique_urls = list(dict.fromkeys(url for url in web_urls if str(url or "").strip()))
    if not unique_urls:
        return {}
    results = await asyncio.gather(
        *[asyncio.to_thread(fetch_console_status, url) for url in unique_urls],
        return_exceptions=True,
    )
    mapping: dict[str, dict[str, Any]] = {}
    for url, result in zip(unique_urls, results, strict=False):
        if isinstance(result, Exception):
            mapping[url] = fetch_console_status("")
            continue
        mapping[url] = result
    return mapping


def fetch_console_audit(
    web_url: str,
    *,
    since_ts: int = 0,
    limit: int = DEFAULT_AUDIT_LIMIT,
    access_token: str = "",
    timeout: float = 2.5,
) -> dict[str, Any]:
    payload = {
        "reachable": False,
        "count": 0,
        "items": [],
        "session_name": "",
        "agent_name": "",
        "host_name": "",
        "ui_version": "",
    }
    audit_url = console_audit_url(
        web_url,
        since_ts=since_ts,
        limit=limit,
        access_token=access_token,
    )
    if not audit_url:
        return payload
    request = Request(
        audit_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "NormanPrime/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ):
        return payload
    if not isinstance(raw, dict):
        return payload
    items = raw.get("items")
    normalized_items = items if isinstance(items, list) else []
    payload.update(
        {
            "reachable": True,
            "count": int(raw.get("count") or len(normalized_items) or 0),
            "items": normalized_items,
            "session_name": str(raw.get("session_name") or "").strip(),
            "agent_name": str(raw.get("agent_name") or "").strip(),
            "host_name": str(raw.get("host_name") or "").strip(),
            "ui_version": str(raw.get("ui_version") or "").strip(),
        }
    )
    return payload


def contains_usage_limit_error(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return (
        "you've hit your usage limit" in text
        or "you hit your usage limit" in text
        or ("usage limit" in text and "try again at" in text)
        or ("usage limit" in text and "send a request to your admin" in text)
    )


def contains_token_reuse_error(value: Any) -> bool:
    text = str(value or "")
    return "refresh_token_reused" in text or (
        "already been used to generate a new access token" in text
    )


def classify_console_credit_assessment(
    status: dict[str, Any],
) -> ConsoleCreditAssessment:
    combined = "\n".join(
        [
            str(status.get("status_message") or ""),
            str(status.get("last_action_detail") or ""),
            str(status.get("response_preview") or ""),
            str(status.get("last_error") or ""),
            str(status.get("auth_summary") or ""),
        ]
    ).strip()

    if contains_usage_limit_error(combined):
        return ConsoleCreditAssessment(
            issue_code="needs_billing",
            issue_label="Needs billing",
            issue_summary="This bot hit its usage limit. Open billing or limits, or switch it to the right account.",
            billing_url=BILLING_URL,
            limits_url=LIMITS_URL,
        )

    if bool(status.get("auth_required")) or contains_token_reuse_error(combined):
        return ConsoleCreditAssessment(
            issue_code="needs_reauth",
            issue_label="Needs reauth",
            issue_summary="This bot needs a fresh sign-in before it can keep working.",
        )

    default_speed = str(status.get("default_speed") or "").strip().lower()
    pending = bool(status.get("pending"))
    queue_depth = int(status.get("queue_depth") or 0)
    state = str(status.get("state") or "").strip().lower()
    if (
        default_speed == "fast"
        and not pending
        and queue_depth <= 0
        and state
        in {
            "ok",
            "idle",
            "ready",
        }
    ):
        return ConsoleCreditAssessment(
            recommended_speed="balanced",
            recommended_speed_reason="Fast is enabled while this bot is idle. Balanced should preserve quota with little downside.",
        )

    return ConsoleCreditAssessment()
