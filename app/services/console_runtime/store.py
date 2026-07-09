from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.console_runtime import (
    ConsoleRuntimeEventRecord,
    ConsoleRuntimeJobRecord,
)
from app.services.console_runtime.events import ConsoleRuntimeEvent
from app.services.console_runtime.kernel import InvalidTransitionError, JobNotFoundError
from app.services.console_runtime.planner import (
    planner_receipt_artifacts,
    planner_receipt_payload,
    planner_receipt_summary,
)
from app.services.console_runtime.types import (
    ConsoleJob,
    ConsoleJobContract,
    ConsoleJobLease,
    ConsoleJobStatus,
    RouteDecision,
    RuntimeModeState,
)
from app.services.norllama.route_outcomes import (
    outcome_from_event_payload,
    route_outcome_event_payload,
    summarize_route_outcomes,
)
from app.services.norllama.specialist_lanes import summarize_specialist_cascade

_CLOUD_ROUTE_PROVIDERS = {
    "anthropic",
    "aws-bedrock",
    "aws_bedrock",
    "bedrock",
    "codex",
    "openai",
    "openai-compatible",
    "openai_compatible",
    "openai-direct",
    "openai_direct",
}
_LOCAL_ROUTE_PROVIDERS = {
    "fake",
    "local",
    "local-ollama",
    "local_ollama",
    "norllama",
    "ollama",
    "runtime-dry-run",
    "shell",
}
_SPARK_HINTS = {
    "spark",
    "spark-150",
    "spark-151",
    "2.150",
    "2.151",
    "192.168.2.150",
    "192.168.2.151",
}
ROUTE_OUTCOME_LEDGER_SOURCE = "norllama_route_outcomes"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value or "")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _provider_key(value: Any) -> str:
    return _lower(value).replace("_", "-")


def _json_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value or {}, dict) else {}


def _json_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean(item) for item in value if _clean(item)]


def _json_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _json_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    clean = _lower(value)
    if not clean:
        return default
    if clean in {"1", "true", "yes", "on", "enabled", "force"}:
        return True
    if clean in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((float(numerator) / float(denominator)) * 100.0, 1)


def _inc(counter: dict[str, int], key: str) -> None:
    clean = _clean(key) or "unknown"
    counter[clean] = counter.get(clean, 0) + 1


def _is_event_sequence_integrity_error(exc: IntegrityError) -> bool:
    message = str(getattr(exc, "orig", exc))
    return "console_runtime_events" in message and "sequence" in message


def _payload_route(payload: dict[str, Any]) -> dict[str, Any]:
    route = _json_dict(payload.get("route"))
    if route:
        return route
    metadata = _json_dict(payload.get("metadata"))
    return _json_dict(metadata.get("norllama_route"))


def _payload_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return _json_dict(payload.get("metadata"))


def _payload_attribution(payload: dict[str, Any]) -> dict[str, Any]:
    route = _payload_route(payload)
    attribution = _json_dict(payload.get("attribution"))
    if attribution:
        return attribution
    return _json_dict(route.get("attribution"))


def _payload_route_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    receipt = _json_dict(payload.get("route_receipt"))
    if receipt:
        return receipt
    nested = _json_dict(payload.get("receipt"))
    receipt = _json_dict(nested.get("route_receipt"))
    if receipt:
        return receipt
    metadata = _payload_metadata(payload)
    return _json_dict(metadata.get("route_receipt"))


def _payload_specialist_cascade(payload: dict[str, Any]) -> dict[str, Any]:
    receipt = _payload_route_receipt(payload)
    cascade = _json_dict(receipt.get("specialist_cascade"))
    if cascade:
        return cascade
    cascade = _json_dict(payload.get("specialist_cascade"))
    if cascade:
        return cascade
    metadata = _payload_metadata(payload)
    return _json_dict(metadata.get("specialist_cascade"))


def _payload_provider(payload: dict[str, Any]) -> str:
    route = _payload_route(payload)
    receipt = _payload_route_receipt(payload)
    return _clean(
        receipt.get("selected_provider")
        or payload.get("selected_provider")
        or payload.get("provider")
        or route.get("provider")
        or route.get("provider_kind")
    )


def _payload_billing_provider(payload: dict[str, Any]) -> str:
    route = _payload_route(payload)
    if _payload_cloud_proxy(payload):
        return _clean(
            route.get("provider")
            or route.get("provider_kind")
            or _payload_provider(payload)
        )
    return _payload_provider(payload)


def _payload_runner(payload: dict[str, Any]) -> str:
    route = _payload_route(payload)
    return _clean(
        payload.get("selected_runner")
        or payload.get("runner")
        or route.get("runner")
        or _payload_provider(payload)
    )


def _payload_model(payload: dict[str, Any]) -> str:
    route = _payload_route(payload)
    receipt = _payload_route_receipt(payload)
    return _clean(
        receipt.get("selected_model")
        or payload.get("selected_model")
        or payload.get("model")
        or route.get("model")
    )


def _payload_lane(payload: dict[str, Any]) -> str:
    route = _payload_route(payload)
    receipt = _payload_route_receipt(payload)
    return _clean(
        receipt.get("phase")
        or payload.get("selected_lane")
        or payload.get("lane")
        or payload.get("capability")
        or route.get("lane")
        or route.get("capability")
    )


def _payload_cloud_proxy(payload: dict[str, Any]) -> bool:
    route = _payload_route(payload)
    receipt = _payload_route_receipt(payload)
    return bool(
        receipt.get("cloud_proxy")
        or payload.get("cloud_proxy")
        or route.get("cloud_proxy")
    )


def _payload_worker_id(payload: dict[str, Any]) -> str:
    route = _payload_route(payload)
    attribution = _payload_attribution(payload)
    receipt = _payload_route_receipt(payload)
    return _clean(
        receipt.get("selected_worker")
        or payload.get("selected_worker_id")
        or payload.get("worker_id")
        or route.get("selected_worker_id")
        or route.get("worker_id")
        or route.get("worker")
        or attribution.get("worker_id")
    )


def _route_is_local(payload: dict[str, Any]) -> bool:
    provider = _provider_key(_payload_provider(payload))
    runner = _provider_key(_payload_runner(payload))
    egress_class = _lower(payload.get("egress_class"))
    return (
        bool(payload.get("local"))
        or egress_class in {"lan", "local"}
        or provider in _LOCAL_ROUTE_PROVIDERS
        or runner in _LOCAL_ROUTE_PROVIDERS
    )


def _route_is_cloud(payload: dict[str, Any]) -> bool:
    provider = _provider_key(_payload_provider(payload))
    billing_provider = _provider_key(_payload_billing_provider(payload))
    runner = _provider_key(_payload_runner(payload))
    egress_class = _lower(payload.get("egress_class"))
    return (
        egress_class == "cloud_llm"
        or _payload_cloud_proxy(payload)
        or provider in _CLOUD_ROUTE_PROVIDERS
        or billing_provider in _CLOUD_ROUTE_PROVIDERS
        or runner in _CLOUD_ROUTE_PROVIDERS
    )


def _event_has_spark_hint(payload: dict[str, Any]) -> bool:
    route = _payload_route(payload)
    metadata = _json_dict(payload.get("metadata"))
    attribution = _payload_attribution(payload)
    parts = [
        payload.get("selected_endpoint"),
        payload.get("endpoint"),
        payload.get("selected_provider"),
        payload.get("selected_runner"),
        payload.get("selected_model"),
        payload.get("worker_id"),
        payload.get("provider"),
        payload.get("model"),
        route.get("endpoint"),
        route.get("worker"),
        route.get("worker_id"),
        attribution.get("worker_id"),
        attribution.get("worker_name"),
        attribution.get("worker_role"),
        attribution.get("worker_endpoint"),
        route.get("provider"),
        route.get("model"),
    ]
    parts.extend(metadata.values())
    haystack = " ".join(_lower(part) for part in parts)
    return any(hint in haystack for hint in _SPARK_HINTS)


def _compact_route_event(event: ConsoleRuntimeEvent) -> dict[str, Any]:
    payload = event.payload
    return {
        "sequence": event.sequence,
        "event_type": event.event_type,
        "summary": event.summary,
        "provider": _payload_provider(payload),
        "runner": _payload_runner(payload),
        "model": _payload_model(payload),
        "lane": _payload_lane(payload),
        "egress_class": _clean(payload.get("egress_class")),
        "local": _route_is_local(payload),
        "cloud_proxy": _payload_cloud_proxy(payload),
        "allowed": bool(payload.get("allowed", True)),
        "worker_id": _payload_worker_id(payload),
        "spark_hint": _event_has_spark_hint(payload),
    }


def _usage_tokens(payload: dict[str, Any]) -> int:
    usage = _json_dict(payload.get("usage"))
    return _json_int(
        usage.get("total_tokens")
        or (
            _json_int(usage.get("input_tokens")) + _json_int(usage.get("output_tokens"))
        )
        or usage.get("raw_total_tokens")
        or usage.get("cumulative_total_tokens")
    )


def _usage_bucket(payload: dict[str, Any]) -> str:
    receipt_bucket = _lower(_payload_route_receipt(payload).get("usage_bucket"))
    if receipt_bucket in {"offline_local", "offline"}:
        return "offline"
    if receipt_bucket in {"openai_codex", "cloud_openai"}:
        return "cloud_openai"
    if receipt_bucket in {"bedrock_amazon", "cloud_amazon"}:
        return "cloud_amazon"
    if receipt_bucket in {"perplexity_web", "perplexity"}:
        return "perplexity"
    if receipt_bucket in {"other_cloud", "cloud_other"}:
        return "cloud_other"
    provider = _provider_key(_payload_billing_provider(payload))
    if _route_is_local(payload) and not _payload_cloud_proxy(payload):
        return "offline"
    if provider in {"bedrock", "aws-bedrock", "aws-bedrock-runtime"}:
        return "cloud_amazon"
    if provider in {
        "codex",
        "openai",
        "openai-compatible",
        "openai-direct",
        "openai-responses",
    }:
        return "cloud_openai"
    if "perplexity" in provider:
        return "perplexity"
    if _route_is_cloud(payload):
        return "cloud_other"
    return "unknown"


def _usage_scope(payload: dict[str, Any], event: ConsoleRuntimeEvent) -> str:
    metadata = _payload_metadata(payload)
    route = _payload_route(payload)
    attribution = _payload_attribution(payload)
    return (
        _clean(metadata.get("session_name"))
        or _clean(metadata.get("session"))
        or _clean(metadata.get("tui"))
        or _clean(metadata.get("agent_name"))
        or _clean(route.get("session_name"))
        or _clean(attribution.get("session_name"))
        or _clean(event.job_id)
    )


def _is_kernel_primary_visible_echo(payload: dict[str, Any]) -> bool:
    usage = _json_dict(payload.get("usage"))
    route_execution = _lower(
        payload.get("route_execution") or usage.get("route_execution")
    )
    if route_execution != "console_runtime_kernel":
        return False
    return _json_bool(payload.get("kernel_primary")) or _json_bool(
        usage.get("kernel_primary")
    )


def _event_day(event: ConsoleRuntimeEvent) -> str:
    created_at = _clean(event.created_at)
    if len(created_at) >= 10:
        return created_at[:10]
    return "unknown"


def _empty_usage_row() -> dict[str, Any]:
    return {
        "model_calls": 0,
        "total_tokens": 0,
        "offline_tokens": 0,
        "cloud_tokens": 0,
        "cloud_llm_tokens": 0,
        "cloud_openai_tokens": 0,
        "cloud_amazon_tokens": 0,
        "perplexity_tokens": 0,
        "third_party_tokens": 0,
        "cloud_other_tokens": 0,
        "unknown_tokens": 0,
    }


def _add_usage(
    row: dict[str, Any],
    *,
    bucket: str,
    tokens: int,
) -> None:
    row["model_calls"] = _json_int(row.get("model_calls")) + 1
    row["total_tokens"] = _json_int(row.get("total_tokens")) + tokens
    if bucket == "offline":
        row["offline_tokens"] = _json_int(row.get("offline_tokens")) + tokens
    elif bucket == "cloud_openai":
        row["cloud_openai_tokens"] = _json_int(row.get("cloud_openai_tokens")) + tokens
        row["cloud_llm_tokens"] = _json_int(row.get("cloud_llm_tokens")) + tokens
        row["cloud_tokens"] = _json_int(row.get("cloud_tokens")) + tokens
    elif bucket == "cloud_amazon":
        row["cloud_amazon_tokens"] = _json_int(row.get("cloud_amazon_tokens")) + tokens
        row["cloud_llm_tokens"] = _json_int(row.get("cloud_llm_tokens")) + tokens
        row["cloud_tokens"] = _json_int(row.get("cloud_tokens")) + tokens
    elif bucket == "perplexity":
        row["perplexity_tokens"] = _json_int(row.get("perplexity_tokens")) + tokens
        row["third_party_tokens"] = _json_int(row.get("third_party_tokens")) + tokens
        row["cloud_tokens"] = _json_int(row.get("cloud_tokens")) + tokens
    elif bucket == "cloud_other":
        row["cloud_other_tokens"] = _json_int(row.get("cloud_other_tokens")) + tokens
        row["cloud_llm_tokens"] = _json_int(row.get("cloud_llm_tokens")) + tokens
        row["cloud_tokens"] = _json_int(row.get("cloud_tokens")) + tokens
    else:
        row["unknown_tokens"] = _json_int(row.get("unknown_tokens")) + tokens


def _finalize_usage_row(row: dict[str, Any]) -> dict[str, Any]:
    total_tokens = _json_int(row.get("total_tokens"))
    offline_tokens = _json_int(row.get("offline_tokens"))
    cloud_tokens = _json_int(row.get("cloud_tokens"))
    cloud_llm_tokens = _json_int(row.get("cloud_llm_tokens"))
    third_party_tokens = _json_int(row.get("third_party_tokens"))
    llm_tokens = offline_tokens + cloud_llm_tokens
    row["offline_percent"] = _pct(offline_tokens, total_tokens)
    row["cloud_percent"] = _pct(cloud_tokens, total_tokens)
    row["cloud_llm_percent"] = _pct(cloud_llm_tokens, llm_tokens)
    row["third_party_percent"] = _pct(third_party_tokens, total_tokens)
    row["local_llm_percent"] = _pct(offline_tokens, llm_tokens)
    return row


def _usage_ledger_summary(events: list[ConsoleRuntimeEvent]) -> dict[str, Any]:
    ledger = _empty_usage_row()
    by_provider: dict[str, int] = {}
    by_model: dict[str, int] = {}
    by_job: dict[str, dict[str, Any]] = {}
    by_scope: dict[str, dict[str, Any]] = {}
    by_day: dict[str, dict[str, Any]] = {}
    latest: dict[str, Any] | None = None

    for event in events:
        if event.event_type != "model.completed":
            continue
        payload = event.payload
        if _is_kernel_primary_visible_echo(payload):
            continue
        tokens = _usage_tokens(payload)
        bucket = _usage_bucket(payload)
        provider = _payload_billing_provider(payload) or _payload_provider(payload)
        model = _payload_model(payload)
        scope = _usage_scope(payload, event)
        day = _event_day(event)

        _add_usage(ledger, bucket=bucket, tokens=tokens)
        if provider:
            by_provider[provider] = by_provider.get(provider, 0) + tokens
        if model:
            by_model[model] = by_model.get(model, 0) + tokens
        job_row = by_job.setdefault(event.job_id, _empty_usage_row())
        _add_usage(job_row, bucket=bucket, tokens=tokens)
        if scope:
            scope_row = by_scope.setdefault(scope, _empty_usage_row())
            _add_usage(scope_row, bucket=bucket, tokens=tokens)
        day_row = by_day.setdefault(day, _empty_usage_row())
        _add_usage(day_row, bucket=bucket, tokens=tokens)
        latest = {
            "sequence": event.sequence,
            "job_id": event.job_id,
            "scope": scope,
            "day": day,
            "provider": provider,
            "model": model,
            "bucket": bucket,
            "tokens": tokens,
        }

    _finalize_usage_row(ledger)
    for row in by_job.values():
        _finalize_usage_row(row)
    for row in by_scope.values():
        _finalize_usage_row(row)
    for row in by_day.values():
        _finalize_usage_row(row)
    return {
        "schema": "norman.console-runtime.usage-ledger.v1",
        **ledger,
        "by_provider": by_provider,
        "by_model": by_model,
        "by_job": by_job,
        "by_scope": by_scope,
        "by_day": by_day,
        "latest": latest,
    }


def _readiness_score(
    *,
    offline_percent: float,
    cloud_llm_percent: float,
    spark_percent: float,
) -> int:
    offline_score = min(100.0, (offline_percent / 80.0) * 100.0)
    cloud_score = max(0.0, 100.0 - max(0.0, cloud_llm_percent - 20.0) * 1.5)
    spark_score = min(100.0, (spark_percent / 50.0) * 100.0)
    return int(
        round((offline_score * 0.55) + (cloud_score * 0.30) + (spark_score * 0.15))
    )


def _local_first_kpi(
    usage_ledger: dict[str, Any],
    *,
    evidence_total: int,
    local_evidence: int,
    cloud_evidence: int,
    spark_evidence: int,
) -> dict[str, Any]:
    offline_tokens = _json_int(usage_ledger.get("offline_tokens"))
    cloud_llm_tokens = _json_int(usage_ledger.get("cloud_llm_tokens"))
    cloud_tokens = _json_int(usage_ledger.get("cloud_tokens"))
    perplexity_tokens = _json_int(usage_ledger.get("perplexity_tokens"))
    llm_tokens = offline_tokens + cloud_llm_tokens
    if llm_tokens:
        offline_percent = _pct(offline_tokens, llm_tokens)
        cloud_llm_percent = _pct(cloud_llm_tokens, llm_tokens)
    else:
        offline_percent = _pct(local_evidence, evidence_total)
        cloud_llm_percent = _pct(cloud_evidence, evidence_total)
    spark_percent = _pct(spark_evidence, evidence_total)

    target_offline = 80
    max_cloud_llm = 20
    target_spark = 50
    if not llm_tokens and not evidence_total:
        status = "no_data"
    elif offline_percent >= target_offline and cloud_llm_percent <= max_cloud_llm:
        status = "on_target"
    elif offline_percent >= 60 and cloud_llm_percent <= 40:
        status = "watch"
    else:
        status = "cloud_heavy"

    reasons: list[str] = []
    if status == "no_data":
        reasons.append("no runtime model usage or route evidence has been recorded")
    elif offline_percent < target_offline:
        reasons.append("local/offline LLM token share is below target")
    if cloud_llm_percent > max_cloud_llm:
        reasons.append("cloud LLM token share is above target")
    if spark_percent < target_spark and evidence_total:
        reasons.append("Spark route evidence is below target")
    if perplexity_tokens:
        reasons.append("Perplexity/web research tokens are tracked separately")

    next_actions: list[str] = []
    if status in {"cloud_heavy", "watch"}:
        next_actions.append("prefer Norllama catalog routes before OpenAI or Bedrock")
    if spark_percent < target_spark:
        next_actions.append(
            "verify Spark workers are reachable and warming expected lanes"
        )
    if cloud_tokens and not cloud_llm_tokens and perplexity_tokens:
        next_actions.append("review scout/search lanes separately from cloud LLM spend")

    return {
        "schema": "norman.console-runtime.local-first-kpi.v1",
        "status": status,
        "readiness_percent": _readiness_score(
            offline_percent=offline_percent,
            cloud_llm_percent=cloud_llm_percent,
            spark_percent=spark_percent,
        )
        if status != "no_data"
        else 0,
        "target_offline_token_percent": target_offline,
        "max_cloud_llm_token_percent": max_cloud_llm,
        "target_spark_evidence_percent": target_spark,
        "offline_token_percent": offline_percent,
        "cloud_llm_token_percent": cloud_llm_percent,
        "spark_evidence_percent": spark_percent,
        "offline_tokens": offline_tokens,
        "cloud_llm_tokens": cloud_llm_tokens,
        "cloud_tokens": cloud_tokens,
        "perplexity_tokens": perplexity_tokens,
        "evidence_total": evidence_total,
        "local_evidence_count": local_evidence,
        "cloud_evidence_count": cloud_evidence,
        "spark_evidence_count": spark_evidence,
        "reasons": reasons,
        "next_actions": next_actions,
    }


def _route_activity_summary(events: list[ConsoleRuntimeEvent]) -> dict[str, Any]:
    route_counts_by_provider: dict[str, int] = {}
    route_counts_by_lane: dict[str, int] = {}
    route_counts_by_worker: dict[str, int] = {}
    model_counts_by_provider: dict[str, int] = {}
    planner_counts_by_provider: dict[str, int] = {}
    planner_counts_by_worker: dict[str, int] = {}

    route_total = 0
    route_allowed = 0
    route_blocked = 0
    route_local = 0
    route_cloud = 0
    route_cloud_proxy = 0
    route_web = 0
    route_spark_hint = 0
    route_offline_safe = 0
    model_completed = 0
    model_local = 0
    model_cloud = 0
    model_tokens = 0
    planner_receipts = 0
    planner_local = 0
    planner_cloud_proxy = 0
    planner_spark_hint = 0
    tool_events = 0
    shell_events = 0
    latest_route: dict[str, Any] | None = None
    latest_model: dict[str, Any] | None = None
    latest_planner: dict[str, Any] | None = None

    for event in events:
        payload = event.payload
        if event.category == "route" or event.event_type.startswith("route."):
            route_total += 1
            provider = _payload_provider(payload)
            lane = _payload_lane(payload)
            worker_id = _payload_worker_id(payload)
            is_local = _route_is_local(payload)
            is_cloud = _route_is_cloud(payload)
            is_cloud_proxy = _payload_cloud_proxy(payload)
            is_allowed = bool(payload.get("allowed", True))
            has_spark_hint = _event_has_spark_hint(payload)
            _inc(route_counts_by_provider, provider)
            _inc(route_counts_by_lane, lane)
            if worker_id:
                _inc(route_counts_by_worker, worker_id)
            route_allowed += int(is_allowed)
            route_blocked += int(not is_allowed)
            route_local += int(is_local)
            route_cloud += int(is_cloud)
            route_cloud_proxy += int(is_cloud_proxy)
            route_web += int(_lower(payload.get("egress_class")) == "web_research")
            route_spark_hint += int(has_spark_hint)
            route_offline_safe += int(is_allowed and is_local and not is_cloud_proxy)
            latest_route = _compact_route_event(event)
        elif event.event_type == "model.completed":
            provider = _payload_provider(payload)
            if _is_kernel_primary_visible_echo(payload):
                continue
            model_completed += 1
            _inc(model_counts_by_provider, provider)
            is_cloud = _route_is_cloud(payload)
            is_local = not _payload_cloud_proxy(payload) and (
                _provider_key(provider) in _LOCAL_ROUTE_PROVIDERS
                or _lower(payload.get("egress_class")) in {"lan", "local"}
            )
            model_local += int(is_local)
            model_cloud += int(is_cloud)
            usage = _json_dict(payload.get("usage"))
            model_tokens += _json_int(
                usage.get("total_tokens")
                or (
                    _json_int(usage.get("input_tokens"))
                    + _json_int(usage.get("output_tokens"))
                )
            )
            latest_model = {
                "sequence": event.sequence,
                "provider": provider,
                "model": _payload_model(payload),
                "tokens": _json_int(
                    usage.get("total_tokens")
                    or (
                        _json_int(usage.get("input_tokens"))
                        + _json_int(usage.get("output_tokens"))
                    )
                ),
                "summary": event.summary,
            }
        elif event.event_type == "planner.receipt":
            provider = _payload_provider(payload)
            worker_id = _payload_worker_id(payload)
            planner_receipts += 1
            _inc(planner_counts_by_provider, provider)
            if worker_id:
                _inc(planner_counts_by_worker, worker_id)
            is_local = _provider_key(provider) in _LOCAL_ROUTE_PROVIDERS
            is_cloud_proxy = _payload_cloud_proxy(payload)
            has_spark_hint = _event_has_spark_hint(payload)
            planner_local += int(is_local)
            planner_cloud_proxy += int(is_cloud_proxy)
            planner_spark_hint += int(has_spark_hint)
            latest_planner = {
                "sequence": event.sequence,
                "provider": provider,
                "model": _payload_model(payload),
                "lane": _payload_lane(payload),
                "status": _clean(payload.get("status")),
                "cloud_proxy": is_cloud_proxy,
                "worker_id": worker_id,
                "spark_hint": has_spark_hint,
                "summary": event.summary,
            }
        elif event.category == "tool":
            tool_events += 1
        elif event.category == "shell":
            shell_events += 1

    evidence_total = route_total + model_completed + planner_receipts
    local_evidence = route_offline_safe + model_local + planner_local
    cloud_evidence = route_cloud + model_cloud + route_cloud_proxy + planner_cloud_proxy
    spark_evidence = route_spark_hint + planner_spark_hint
    usage_ledger = _usage_ledger_summary(events)
    local_first_kpi = _local_first_kpi(
        usage_ledger,
        evidence_total=evidence_total,
        local_evidence=local_evidence,
        cloud_evidence=cloud_evidence,
        spark_evidence=spark_evidence,
    )

    return {
        "schema": "norman.console-runtime.route-summary.v1",
        "event_count": len(events),
        "usage_ledger": usage_ledger,
        "local_first_kpi": local_first_kpi,
        "evidence_total": evidence_total,
        "local_evidence_count": local_evidence,
        "cloud_evidence_count": cloud_evidence,
        "spark_evidence_count": spark_evidence,
        "local_evidence_percent": _pct(local_evidence, evidence_total),
        "cloud_evidence_percent": _pct(cloud_evidence, evidence_total),
        "route": {
            "total": route_total,
            "allowed": route_allowed,
            "blocked": route_blocked,
            "local_or_lan": route_local,
            "offline_safe": route_offline_safe,
            "cloud_llm": route_cloud,
            "cloud_proxy": route_cloud_proxy,
            "web_research": route_web,
            "spark_hint": route_spark_hint,
            "local_percent": _pct(route_local, route_total),
            "offline_safe_percent": _pct(route_offline_safe, route_total),
            "by_provider": route_counts_by_provider,
            "by_lane": route_counts_by_lane,
            "by_worker": route_counts_by_worker,
            "latest": latest_route,
        },
        "model": {
            "completed": model_completed,
            "local": model_local,
            "cloud": model_cloud,
            "tokens": model_tokens,
            "local_percent": _pct(model_local, model_completed),
            "by_provider": model_counts_by_provider,
            "latest": latest_model,
        },
        "planner": {
            "receipts": planner_receipts,
            "local": planner_local,
            "cloud_proxy": planner_cloud_proxy,
            "spark_hint": planner_spark_hint,
            "local_percent": _pct(planner_local, planner_receipts),
            "by_provider": planner_counts_by_provider,
            "by_worker": planner_counts_by_worker,
            "latest": latest_planner,
        },
        "workers": {
            "by_id": {
                worker_id: route_counts_by_worker.get(worker_id, 0)
                + planner_counts_by_worker.get(worker_id, 0)
                for worker_id in sorted(
                    set(route_counts_by_worker) | set(planner_counts_by_worker)
                )
            },
            "route": route_counts_by_worker,
            "planner": planner_counts_by_worker,
        },
        "execution_events": {
            "tool": tool_events,
            "shell": shell_events,
        },
    }


def _local_first_proof(
    events: list[ConsoleRuntimeEvent], *, session_limit: int = 20
) -> dict[str, Any]:
    sessions: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for event in events:
        if event.event_type not in {
            "model.completed",
            "planner.receipt",
            "route.decision",
            "route.local-llm-outcome",
        } and not event.event_type.startswith("route."):
            continue
        payload = event.payload
        session_id = _usage_scope(payload, event) or event.job_id
        if session_id not in sessions:
            sessions[session_id] = {
                "session": session_id,
                "job_id": event.job_id,
                "last_sequence": event.sequence,
                "last_event_at": event.created_at,
                "local_tokens": 0,
                "openai_codex_tokens": 0,
                "bedrock_amazon_tokens": 0,
                "perplexity_web_tokens": 0,
                "other_cloud_tokens": 0,
                "cloud_proxy_tokens": 0,
                "spark_evidence_count": 0,
                "providers": {},
                "models_by_phase": {},
                "workers": {},
                "fallbacks": [],
                "verifier_results": {},
                "output_shapes": {},
                "specialist_required_count": 0,
                "specialist_evidence_count": 0,
                "specialist_lanes": {},
                "deterministic_experts": {},
                "specialist_statuses": {},
                "specialist_live_smoke_statuses": {},
                "specialist_proof_states": {},
                "specialist_benchmark_fresh_count": 0,
                "specialist_production_ready_count": 0,
                "receipt_audit": {},
                "receipt_audit_failures": {},
                "receipt_audit_pass_count": 0,
                "receipt_audit_fail_count": 0,
            }
            order.append(session_id)
        row = sessions[session_id]
        row["last_sequence"] = max(_json_int(row.get("last_sequence")), event.sequence)
        row["last_event_at"] = event.created_at
        provider = _payload_provider(payload)
        model = _payload_model(payload)
        worker_id = _payload_worker_id(payload)
        phase = _payload_lane(payload) or event.category or event.event_type
        tokens = _usage_tokens(payload)
        bucket = _usage_bucket(payload)
        if bucket == "offline":
            row["local_tokens"] += tokens
        elif bucket == "cloud_openai":
            row["openai_codex_tokens"] += tokens
        elif bucket == "cloud_amazon":
            row["bedrock_amazon_tokens"] += tokens
        elif bucket == "perplexity":
            row["perplexity_web_tokens"] += tokens
        elif bucket == "cloud_other":
            row["other_cloud_tokens"] += tokens
        if _payload_cloud_proxy(payload):
            row["cloud_proxy_tokens"] += tokens
        if provider:
            _inc(row["providers"], provider)
        if model:
            models = row["models_by_phase"].setdefault(phase, [])
            if model not in models:
                models.append(model)
        if worker_id:
            _inc(row["workers"], worker_id)
        if _event_has_spark_hint(payload):
            row["spark_evidence_count"] += 1
        receipt = _payload_route_receipt(payload)
        fallback_reason = _clean(receipt.get("fallback_reason"))
        if fallback_reason and fallback_reason not in row["fallbacks"]:
            row["fallbacks"].append(fallback_reason)
        verifier = _clean(
            payload.get("verifier_result") or receipt.get("verifier_result")
        )
        if verifier:
            _inc(row["verifier_results"], verifier)
        shape = _clean(payload.get("output_shape") or receipt.get("output_shape"))
        if shape:
            _inc(row["output_shapes"], shape)
        receipt_audit = _json_dict(
            payload.get("receipt_audit") or receipt.get("receipt_audit")
        )
        if receipt_audit:
            audit_status = _lower(receipt_audit.get("status")) or "unknown"
            _inc(row["receipt_audit"], audit_status)
            if bool(receipt_audit.get("pass")):
                row["receipt_audit_pass_count"] += 1
            else:
                row["receipt_audit_fail_count"] += 1
                for failure in receipt_audit.get("failures") or []:
                    _inc(row["receipt_audit_failures"], _clean(failure))
        specialist_cascade = _payload_specialist_cascade(payload)
        if specialist_cascade:
            specialist_summary = summarize_specialist_cascade(specialist_cascade)
            row["specialist_required_count"] += _json_int(
                specialist_summary.get("lane_count")
            ) + _json_int(specialist_summary.get("expert_count"))
            for lane in specialist_summary.get("lanes") or []:
                _inc(row["specialist_lanes"], lane)
            for expert in specialist_summary.get("deterministic_experts") or []:
                _inc(row["deterministic_experts"], expert)
            for item in specialist_cascade.get("lanes") or []:
                if not isinstance(item, dict):
                    continue
                status = _lower(item.get("status")) or "pending"
                if status != "not_requested":
                    _inc(row["specialist_statuses"], status)
                    live_smoke = (
                        item.get("live_smoke_test")
                        if isinstance(item.get("live_smoke_test"), dict)
                        else {}
                    )
                    smoke = _lower(live_smoke.get("status"))
                    if smoke:
                        _inc(row["specialist_live_smoke_statuses"], smoke)
                    proof_state = _lower(item.get("proof_state"))
                    if proof_state:
                        _inc(row["specialist_proof_states"], proof_state)
                        if proof_state == "production":
                            row["specialist_production_ready_count"] += 1
                    benchmark = item.get("benchmark_evidence")
                    if isinstance(benchmark, dict) and benchmark.get("fresh"):
                        row["specialist_benchmark_fresh_count"] += 1
                if status in {"complete", "pass", "passed", "fail", "failed", "error"}:
                    row["specialist_evidence_count"] += 1
            for item in specialist_cascade.get("deterministic_experts") or []:
                if not isinstance(item, dict):
                    continue
                status = _lower(item.get("status")) or "pending"
                if status != "not_requested":
                    _inc(row["specialist_statuses"], status)
                if status in {"complete", "pass", "passed", "fail", "failed", "error"}:
                    row["specialist_evidence_count"] += 1
    rows = sorted(
        sessions.values(),
        key=lambda item: _json_int(item.get("last_sequence")),
        reverse=True,
    )[: max(1, min(int(session_limit or 20), 100))]
    totals = {
        "local_tokens": sum(_json_int(row.get("local_tokens")) for row in rows),
        "openai_codex_tokens": sum(
            _json_int(row.get("openai_codex_tokens")) for row in rows
        ),
        "bedrock_amazon_tokens": sum(
            _json_int(row.get("bedrock_amazon_tokens")) for row in rows
        ),
        "perplexity_web_tokens": sum(
            _json_int(row.get("perplexity_web_tokens")) for row in rows
        ),
        "other_cloud_tokens": sum(
            _json_int(row.get("other_cloud_tokens")) for row in rows
        ),
        "cloud_proxy_tokens": sum(
            _json_int(row.get("cloud_proxy_tokens")) for row in rows
        ),
        "spark_evidence_count": sum(
            _json_int(row.get("spark_evidence_count")) for row in rows
        ),
        "specialist_required_count": sum(
            _json_int(row.get("specialist_required_count")) for row in rows
        ),
        "specialist_evidence_count": sum(
            _json_int(row.get("specialist_evidence_count")) for row in rows
        ),
        "specialist_benchmark_fresh_count": sum(
            _json_int(row.get("specialist_benchmark_fresh_count")) for row in rows
        ),
        "specialist_production_ready_count": sum(
            _json_int(row.get("specialist_production_ready_count")) for row in rows
        ),
        "receipt_audit_pass_count": sum(
            _json_int(row.get("receipt_audit_pass_count")) for row in rows
        ),
        "receipt_audit_fail_count": sum(
            _json_int(row.get("receipt_audit_fail_count")) for row in rows
        ),
    }
    return {
        "schema": "norman.console-runtime.local-first-proof.v1",
        "session_count": len(rows),
        "sessions": rows,
        "totals": totals,
        "release_gate": {
            "proves_local_first": bool(rows)
            and totals["local_tokens"]
            >= (
                totals["openai_codex_tokens"]
                + totals["bedrock_amazon_tokens"]
                + totals["other_cloud_tokens"]
            ),
            "has_spark_evidence": totals["spark_evidence_count"] > 0,
            "specialist_cascade_visible": totals["specialist_required_count"] > 0,
            "has_specialist_evidence": totals["specialist_evidence_count"] > 0,
            "specialist_proof_ready": (totals["specialist_production_ready_count"] > 0),
            "has_specialist_benchmark_evidence": (
                totals["specialist_benchmark_fresh_count"] > 0
            ),
            "receipt_audit_passed": totals["receipt_audit_pass_count"] > 0
            and totals["receipt_audit_fail_count"] == 0,
            "cloud_proxy_visible": totals["cloud_proxy_tokens"] > 0,
        },
    }


_TERMINAL_STATES = {
    ConsoleJobStatus.BLOCKED.value,
    ConsoleJobStatus.CANCELED.value,
    ConsoleJobStatus.DONE.value,
    ConsoleJobStatus.FAILED.value,
}


def _is_tui_stream_record(record: ConsoleRuntimeJobRecord) -> bool:
    metadata = _json_dict(record.metadata_json)
    contract = _json_dict(record.contract_json)
    authority_flags = _json_dict(contract.get("authority_flags"))
    contract_metadata = _json_dict(contract.get("metadata"))
    route_policy = _json_dict(contract.get("route_policy"))
    sources = {
        _clean(metadata.get("source")),
        _clean(contract_metadata.get("source")),
        _clean(authority_flags.get("source")),
    }
    if "agent_console_web" in sources:
        return not _is_executable_tui_turn_record(
            record,
            metadata=metadata,
            contract_metadata=contract_metadata,
            authority_flags=authority_flags,
            route_policy=route_policy,
        )
    if ROUTE_OUTCOME_LEDGER_SOURCE in sources:
        return True
    return (
        _clean(route_policy.get("runtime")) == "shell"
        and _clean(route_policy.get("planner")) == "norllama"
        and _clean(route_policy.get("model_proxy")) == "norllama"
        and _clean(record.objective).lower().startswith("live tui runtime stream")
    )


def _is_executable_tui_turn_record(
    record: ConsoleRuntimeJobRecord,
    *,
    metadata: dict[str, Any],
    contract_metadata: dict[str, Any],
    authority_flags: dict[str, Any],
    route_policy: dict[str, Any],
) -> bool:
    objective = _clean(record.objective).lower()
    if objective.startswith("live tui runtime stream"):
        return False
    kinds = {
        _clean(metadata.get("kind")),
        _clean(contract_metadata.get("kind")),
        _clean(authority_flags.get("kind")),
    }
    if "tui_turn_shadow" not in kinds:
        return False
    kernel_execution_enabled = any(
        _json_bool(container.get("kernel_execution_enabled"))
        for container in (metadata, contract_metadata, authority_flags, route_policy)
    )
    kernel_execution_candidate = any(
        _json_bool(container.get("kernel_execution_candidate"))
        for container in (metadata, contract_metadata, authority_flags, route_policy)
    )
    continuous_goal_candidate = any(
        _json_bool(container.get("continuous_goal_candidate"))
        for container in (metadata, contract_metadata, authority_flags, route_policy)
    )
    if not (
        kernel_execution_enabled
        and kernel_execution_candidate
        and continuous_goal_candidate
    ):
        return False
    provider = _provider_key(
        route_policy.get("provider")
        or route_policy.get("preferred_provider")
        or route_policy.get("provider_surface")
        or route_policy.get("model_proxy")
    )
    return provider in _LOCAL_ROUTE_PROVIDERS


def _to_job(record: ConsoleRuntimeJobRecord) -> ConsoleJob:
    lease = None
    lease_json = _json_dict(record.lease_json)
    if lease_json:
        lease = ConsoleJobLease(
            worker_id=_clean(lease_json.get("worker_id")),
            leased_at=_clean(lease_json.get("leased_at")),
            expires_at=_clean(lease_json.get("expires_at")),
        )
    return ConsoleJob(
        job_id=record.job_id,
        contract=ConsoleJobContract(**_json_dict(record.contract_json)),
        status=ConsoleJobStatus(_clean(record.status) or "queued"),
        created_at=_iso(record.created_at),
        updated_at=_iso(record.updated_at),
        lease=lease,
        checkpoints=_json_list(record.checkpoints_json),
        artifacts=_json_list(record.artifacts_json),
        last_error=_clean(record.last_error),
        metadata=_json_dict(record.metadata_json),
    )


def _to_event(record: ConsoleRuntimeEventRecord) -> ConsoleRuntimeEvent:
    return ConsoleRuntimeEvent(
        job_id=record.job_id,
        event_type=record.event_type,
        payload=_json_dict(record.payload_json),
        sequence=record.sequence,
        category=record.category,
        summary=record.summary,
        detail=record.detail,
        visibility=record.visibility,
        event_id=record.event_id,
        created_at=_iso(record.created_at),
    )


class DbConsoleRuntimeStore:
    """Durable console runtime job and event store."""

    def route_outcome_job_id(self, *, user_id: int) -> str:
        return f"norllama-route-outcomes-u{int(user_id)}"

    def create_job(
        self,
        db: Session,
        *,
        user_id: int,
        contract: ConsoleJobContract,
        job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConsoleJob:
        job = ConsoleJob.new(contract=contract, job_id=job_id)
        if self._job_record(db, user_id=user_id, job_id=job.job_id) is not None:
            raise InvalidTransitionError(f"Job already exists: {job.job_id}")
        now = _utc_now()
        record = ConsoleRuntimeJobRecord(
            user_id=user_id,
            job_id=job.job_id,
            status=job.status.value,
            objective=contract.objective,
            contract_json=contract.as_dict(),
            metadata_json=dict(metadata or {}),
            lease_json=None,
            checkpoints_json=[],
            artifacts_json=[],
            last_error="",
            created_at=now,
            updated_at=now,
        )
        db.add(record)
        db.flush()
        self._append_event_record(
            db,
            user_id=user_id,
            job_id=job.job_id,
            event_type="job.created",
            payload={
                "objective": contract.objective,
                "done_when": list(contract.done_when),
                "required_artifacts": list(contract.required_artifacts),
            },
            summary="Job created",
            created_at=now,
        )
        db.commit()
        db.refresh(record)
        return _to_job(record)

    def get_job(self, db: Session, *, user_id: int, job_id: str) -> ConsoleJob:
        record = self._job_record(db, user_id=user_id, job_id=job_id)
        if record is None:
            raise JobNotFoundError(f"Unknown job: {job_id}")
        return _to_job(record)

    def list_jobs(
        self,
        db: Session,
        *,
        user_id: int,
        limit: int = 100,
        include_done: bool = True,
    ) -> list[ConsoleJob]:
        query = db.query(ConsoleRuntimeJobRecord).filter(
            ConsoleRuntimeJobRecord.user_id == user_id
        )
        if not include_done:
            query = query.filter(ConsoleRuntimeJobRecord.status != "done")
        records = (
            query.order_by(ConsoleRuntimeJobRecord.id.desc())
            .limit(max(1, min(int(limit or 100), 1000)))
            .all()
        )
        return [_to_job(record) for record in records]

    def list_runnable_jobs(
        self,
        db: Session,
        *,
        limit: int = 10,
    ) -> list[tuple[int, ConsoleJob]]:
        records = (
            db.query(ConsoleRuntimeJobRecord)
            .filter(
                ConsoleRuntimeJobRecord.status.in_(
                    [
                        ConsoleJobStatus.QUEUED.value,
                        ConsoleJobStatus.CHECKPOINTED.value,
                    ]
                )
            )
            .order_by(ConsoleRuntimeJobRecord.id.asc())
            .limit(max(100, min(int(limit or 10) * 5, 1000)))
            .all()
        )
        runnable = []
        max_items = max(1, min(int(limit or 10), 100))
        for record in records:
            if _is_tui_stream_record(record):
                continue
            runnable.append((int(record.user_id), _to_job(record)))
            if len(runnable) >= max_items:
                break
        return runnable

    def lease_job(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        worker_id: str,
        lease_seconds: int = 900,
    ) -> ConsoleJob:
        last_error: IntegrityError | None = None
        for _attempt in range(5):
            record = self._required_job_record(db, user_id=user_id, job_id=job_id)
            self._ensure_not_terminal(record)
            if record.status not in {
                ConsoleJobStatus.QUEUED.value,
                ConsoleJobStatus.CHECKPOINTED.value,
            }:
                raise InvalidTransitionError(
                    f"Cannot lease job {job_id} from state {record.status}"
                )
            now = _utc_now()
            expires_at = now + timedelta(seconds=max(1, int(lease_seconds or 1)))
            record.lease_json = {
                "worker_id": _clean(worker_id) or "runtime-worker",
                "leased_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
            }
            record.status = ConsoleJobStatus.LEASED.value
            record.updated_at = now
            self._append_event_record(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="job.leased",
                payload=record.lease_json,
                summary=f"Leased to {record.lease_json['worker_id']}",
                created_at=now,
            )
            db.add(record)
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                if not _is_event_sequence_integrity_error(exc):
                    raise
                last_error = exc
                continue
            db.refresh(record)
            return _to_job(record)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Console runtime job lease failed without an error.")

    def start_job(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
    ) -> ConsoleJob:
        last_error: IntegrityError | None = None
        for _attempt in range(5):
            record = self._required_job_record(db, user_id=user_id, job_id=job_id)
            self._ensure_not_terminal(record)
            if record.status not in {
                ConsoleJobStatus.LEASED.value,
                ConsoleJobStatus.CHECKPOINTED.value,
            }:
                raise InvalidTransitionError(
                    f"Cannot start job {job_id} from state {record.status}"
                )
            record.status = ConsoleJobStatus.RUNNING.value
            record.updated_at = _utc_now()
            self._append_event_record(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type="job.started",
                payload={},
                summary="Job started",
                created_at=record.updated_at,
            )
            db.add(record)
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                if not _is_event_sequence_integrity_error(exc):
                    raise
                last_error = exc
                continue
            db.refresh(record)
            return _to_job(record)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Console runtime job start failed without an error.")

    def events_after(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str | None = None,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> list[ConsoleRuntimeEvent]:
        after = max(0, int(after_sequence or 0))
        query = db.query(ConsoleRuntimeEventRecord).filter(
            ConsoleRuntimeEventRecord.user_id == user_id,
            ConsoleRuntimeEventRecord.sequence > after,
        )
        if job_id:
            query = query.filter(ConsoleRuntimeEventRecord.job_id == job_id)
        records = (
            query.order_by(
                ConsoleRuntimeEventRecord.sequence.asc(),
                ConsoleRuntimeEventRecord.id.asc(),
            )
            .limit(max(1, min(int(limit or 200), 1000)))
            .all()
        )
        return [_to_event(record) for record in records]

    def append_event(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        summary: str = "",
        detail: str = "",
        visibility: str = "timeline",
        artifacts: Iterable[str] | None = None,
    ) -> ConsoleRuntimeEvent:
        last_error: IntegrityError | None = None
        for _attempt in range(5):
            record = self._job_record(db, user_id=user_id, job_id=job_id)
            if record is None:
                raise JobNotFoundError(f"Unknown job: {job_id}")
            event = self._append_event_record(
                db,
                user_id=user_id,
                job_id=job_id,
                event_type=event_type,
                payload=payload or {},
                summary=summary,
                detail=detail,
                visibility=visibility,
            )
            added = []
            if artifacts:
                current = _json_list(record.artifacts_json)
                for artifact in artifacts:
                    value = _clean(artifact)
                    if value and value not in current:
                        current.append(value)
                        added.append(value)
                if added:
                    record.artifacts_json = current
            record.updated_at = _utc_now()
            db.add(record)
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                if not _is_event_sequence_integrity_error(exc):
                    raise
                last_error = exc
                continue
            db.refresh(event)
            return _to_event(event)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Console runtime event append failed without an error.")

    def ensure_route_outcome_job(
        self,
        db: Session,
        *,
        user_id: int,
    ) -> ConsoleJob:
        job_id = self.route_outcome_job_id(user_id=user_id)
        record = self._job_record(db, user_id=user_id, job_id=job_id)
        if record is not None:
            return _to_job(record)
        return self.create_job(
            db,
            user_id=user_id,
            job_id=job_id,
            contract=ConsoleJobContract(
                objective="Norllama local route outcome ledger",
                done_when=[
                    "Local model route outcomes are retained for fleet-wide routing proof.",
                ],
                success_metrics=[
                    "TUIs can report local model success, failure, worker, and cooldown evidence.",
                ],
                question_budget=0,
                authority_flags={"source": ROUTE_OUTCOME_LEDGER_SOURCE},
                route_policy={
                    "runtime": "norllama",
                    "planner": "norllama",
                    "model_proxy": "norllama",
                },
                metadata={"source": ROUTE_OUTCOME_LEDGER_SOURCE},
            ),
            metadata={"source": ROUTE_OUTCOME_LEDGER_SOURCE},
        )

    def append_route_outcome(
        self,
        db: Session,
        *,
        user_id: int,
        outcome: dict[str, Any],
    ) -> ConsoleRuntimeEvent:
        job = self.ensure_route_outcome_job(db, user_id=user_id)
        payload = route_outcome_event_payload(outcome)
        normalized = outcome_from_event_payload(payload)
        model = _clean(normalized.get("model"))
        status = _clean(normalized.get("status"))
        tui = _clean(normalized.get("tui") or normalized.get("session"))
        summary = "Local route outcome"
        if model or status:
            summary = "Local route outcome: " + " ".join(
                part for part in (model, status) if part
            )
        detail = _clean(normalized.get("reason"))
        if tui:
            detail = f"{tui}: {detail}" if detail else tui
        return self.append_event(
            db,
            user_id=user_id,
            job_id=job.job_id,
            event_type="route.local-llm-outcome",
            payload=payload,
            summary=summary,
            detail=detail,
        )

    def route_outcome_summary(
        self,
        db: Session,
        *,
        user_id: int,
        limit: int = 1000,
        cooldown_seconds: int = 900,
    ) -> dict[str, Any]:
        job_id = self.route_outcome_job_id(user_id=user_id)
        record = self._job_record(db, user_id=user_id, job_id=job_id)
        if record is None:
            return summarize_route_outcomes(
                [],
                cooldown_seconds=cooldown_seconds,
            )
        events = self._events_for_job(db, user_id=user_id, job_id=job_id)
        if limit and len(events) > limit:
            events = events[-max(1, min(int(limit or 1000), 10000)) :]
        outcomes = [
            outcome_from_event_payload(event.payload)
            for event in events
            if event.event_type == "route.local-llm-outcome"
        ]
        summary = summarize_route_outcomes(
            outcomes,
            cooldown_seconds=cooldown_seconds,
        )
        summary["job_id"] = job_id
        return summary

    def route_outcomes(
        self,
        db: Session,
        *,
        user_id: int,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        job_id = self.route_outcome_job_id(user_id=user_id)
        record = self._job_record(db, user_id=user_id, job_id=job_id)
        if record is None:
            return []
        events = self._events_for_job(db, user_id=user_id, job_id=job_id)
        if limit and len(events) > limit:
            events = events[-max(1, min(int(limit or 1000), 10000)) :]
        return [
            outcome_from_event_payload(event.payload)
            for event in events
            if event.event_type == "route.local-llm-outcome"
        ]

    def record_policy_state(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        policy_state: RuntimeModeState | dict[str, Any],
        summary: str = "",
        detail: str = "",
    ) -> ConsoleRuntimeEvent:
        payload = (
            policy_state.as_dict()
            if hasattr(policy_state, "as_dict")
            else dict(policy_state or {})
        )
        mode = _clean(payload.get("active_mode"))
        return self.append_event(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="policy.mode_selected",
            payload=payload,
            summary=summary
            or (f"Runtime mode: {mode}" if mode else "Runtime mode selected"),
            detail=detail,
        )

    def record_policy_block(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        reason: str,
        policy_state: RuntimeModeState | dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConsoleRuntimeEvent:
        payload: dict[str, Any] = {"reason": reason, "metadata": dict(metadata or {})}
        if policy_state is not None:
            payload["policy_state"] = (
                policy_state.as_dict()
                if hasattr(policy_state, "as_dict")
                else dict(policy_state or {})
            )
        return self.append_event(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="policy.egress_blocked",
            payload=payload,
            summary="Runtime policy blocked route",
            detail=reason,
        )

    def record_route_decision(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        decision: RouteDecision | dict[str, Any],
        event_type: str = "route.decided",
        summary: str = "",
        detail: str = "",
    ) -> ConsoleRuntimeEvent:
        payload = (
            decision.as_dict() if hasattr(decision, "as_dict") else dict(decision or {})
        )
        provider = _clean(payload.get("selected_provider"))
        model = _clean(payload.get("selected_model"))
        route_summary = "Route decided"
        if provider or model:
            route_summary = "Route decided: " + " ".join(
                part for part in (provider, model) if part
            )
        return self.append_event(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type=event_type,
            payload=payload,
            summary=summary or route_summary,
            detail=detail or "; ".join(payload.get("blocked_reasons") or []),
        )

    def checkpoint_job(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        summary: str,
        artifacts: Iterable[str] | None = None,
    ) -> ConsoleJob:
        record = self._required_job_record(db, user_id=user_id, job_id=job_id)
        self._ensure_not_terminal(record)
        if record.status not in {
            ConsoleJobStatus.LEASED.value,
            ConsoleJobStatus.RUNNING.value,
            ConsoleJobStatus.VERIFYING.value,
            ConsoleJobStatus.WAITING_APPROVAL.value,
        }:
            raise InvalidTransitionError(
                f"Cannot checkpoint job {job_id} from state {record.status}"
            )
        added_artifacts = self._record_artifacts(record, artifacts or [])
        checkpoints = _json_list(record.checkpoints_json)
        checkpoints.append(_clean(summary) or "Checkpointed")
        record.checkpoints_json = checkpoints
        record.status = ConsoleJobStatus.CHECKPOINTED.value
        record.updated_at = _utc_now()
        self._append_event_record(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="job.checkpointed",
            payload={"summary": summary, "artifacts": added_artifacts},
            summary=summary,
            created_at=record.updated_at,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return _to_job(record)

    def block_job(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        reason: str,
    ) -> ConsoleJob:
        record = self._required_job_record(db, user_id=user_id, job_id=job_id)
        self._ensure_not_terminal(record)
        record.status = ConsoleJobStatus.BLOCKED.value
        record.last_error = _clean(reason)
        record.updated_at = _utc_now()
        self._append_event_record(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="job.blocked",
            payload={"reason": record.last_error},
            summary="Job blocked",
            detail=record.last_error,
            created_at=record.updated_at,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return _to_job(record)

    def complete_job(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        summary: str = "",
        artifacts: Iterable[str] | None = None,
    ) -> ConsoleJob:
        record = self._required_job_record(db, user_id=user_id, job_id=job_id)
        self._ensure_not_terminal(record)
        added_artifacts = self._record_artifacts(record, artifacts or [])
        job = _to_job(record)
        missing = [
            artifact
            for artifact in job.contract.required_artifacts
            if artifact not in set(job.artifacts)
        ]
        if missing:
            raise InvalidTransitionError(
                "Cannot complete job before required artifacts exist: "
                + ", ".join(missing)
            )
        record.status = ConsoleJobStatus.DONE.value
        record.updated_at = _utc_now()
        self._append_event_record(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="job.completed",
            payload={"summary": summary, "artifacts": added_artifacts},
            summary=summary or "Job completed",
            created_at=record.updated_at,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return _to_job(record)

    def fail_job(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        error: str,
    ) -> ConsoleJob:
        record = self._required_job_record(db, user_id=user_id, job_id=job_id)
        if record.status in {
            ConsoleJobStatus.CANCELED.value,
            ConsoleJobStatus.DONE.value,
        }:
            raise InvalidTransitionError(
                f"Cannot fail job {job_id} from state {record.status}"
            )
        record.status = ConsoleJobStatus.FAILED.value
        record.last_error = _clean(error)
        record.updated_at = _utc_now()
        self._append_event_record(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="job.failed",
            payload={"error": record.last_error},
            summary="Job failed",
            detail=record.last_error,
            created_at=record.updated_at,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return _to_job(record)

    def require_approval(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        reason: str,
        requested_by: str = "",
    ) -> ConsoleJob:
        record = self._required_job_record(db, user_id=user_id, job_id=job_id)
        self._ensure_not_terminal(record)
        record.status = ConsoleJobStatus.WAITING_APPROVAL.value
        record.updated_at = _utc_now()
        self._append_event_record(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="job.approval_required",
            payload={"reason": reason, "requested_by": requested_by},
            summary="Approval required",
            detail=reason,
            created_at=record.updated_at,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return _to_job(record)

    def approve_job(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        reason: str = "",
        approved_by: str = "",
    ) -> ConsoleJob:
        record = self._required_job_record(db, user_id=user_id, job_id=job_id)
        self._ensure_not_terminal(record)
        if record.status != ConsoleJobStatus.WAITING_APPROVAL.value:
            raise InvalidTransitionError(
                f"Cannot approve job {job_id} from state {record.status}"
            )
        record.status = ConsoleJobStatus.CHECKPOINTED.value
        record.lease_json = None
        record.updated_at = _utc_now()
        self._append_event_record(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="approval.approved",
            payload={"reason": reason, "approved_by": approved_by},
            summary="Approval granted",
            detail=reason,
            created_at=record.updated_at,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return _to_job(record)

    def reject_approval(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        reason: str = "",
        rejected_by: str = "",
    ) -> ConsoleJob:
        record = self._required_job_record(db, user_id=user_id, job_id=job_id)
        self._ensure_not_terminal(record)
        if record.status != ConsoleJobStatus.WAITING_APPROVAL.value:
            raise InvalidTransitionError(
                f"Cannot reject approval for job {job_id} from state {record.status}"
            )
        record.status = ConsoleJobStatus.BLOCKED.value
        record.lease_json = None
        record.last_error = _clean(reason) or "Approval rejected"
        record.updated_at = _utc_now()
        self._append_event_record(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="approval.rejected",
            payload={"reason": record.last_error, "rejected_by": rejected_by},
            summary="Approval rejected",
            detail=record.last_error,
            created_at=record.updated_at,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return _to_job(record)

    def record_planner_receipt(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        receipt: dict[str, Any],
        capabilities: dict[str, Any] | None = None,
        summary: str = "",
        detail: str = "",
        artifacts: Iterable[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConsoleRuntimeEvent:
        record = self._job_record(db, user_id=user_id, job_id=job_id)
        if record is None:
            raise JobNotFoundError(f"Unknown job: {job_id}")
        artifact_list = planner_receipt_artifacts(receipt, list(artifacts or []))
        event = self._append_event_record(
            db,
            user_id=user_id,
            job_id=job_id,
            event_type="planner.receipt",
            payload=planner_receipt_payload(
                receipt,
                capabilities=capabilities,
                metadata=metadata,
                artifacts=artifact_list,
            ),
            summary=summary or planner_receipt_summary(receipt),
            detail=detail,
        )
        added = []
        if artifact_list:
            current = _json_list(record.artifacts_json)
            for artifact in artifact_list:
                value = _clean(artifact)
                if value and value not in current:
                    current.append(value)
                    added.append(value)
            if added:
                record.artifacts_json = current
        record.updated_at = _utc_now()
        db.add(record)
        db.commit()
        db.refresh(event)
        return _to_event(event)

    def activity_snapshot(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        job = self.get_job(db, user_id=user_id, job_id=job_id)
        all_events = self._events_for_job(db, user_id=user_id, job_id=job_id)
        events = self.events_after(
            db,
            user_id=user_id,
            job_id=job_id,
            after_sequence=after_sequence,
            limit=limit,
        )
        category_counts: dict[str, int] = {}
        for event in all_events:
            category_counts[event.category] = category_counts.get(event.category, 0) + 1
        next_after = events[-1].sequence if events else int(after_sequence or 0)
        return {
            "job": job.as_dict(),
            "events": [event.as_dict() for event in events],
            "event_count": len(all_events),
            "category_counts": category_counts,
            "latest_event": all_events[-1].as_dict() if all_events else None,
            "next_after": next_after,
            "route_summary": _route_activity_summary(all_events),
        }

    def route_activity_summary(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        if job_id:
            self.get_job(db, user_id=user_id, job_id=job_id)
            events = self._events_for_job(db, user_id=user_id, job_id=job_id)
        else:
            events = self._events_for_user(
                db,
                user_id=user_id,
                limit=limit,
            )
        summary = _route_activity_summary(events)
        summary["job_id"] = job_id or ""
        return summary

    def local_first_proof(
        self,
        db: Session,
        *,
        user_id: int,
        limit: int = 1000,
        session_limit: int = 20,
    ) -> dict[str, Any]:
        events = self._events_for_user(
            db,
            user_id=user_id,
            limit=limit,
        )
        return _local_first_proof(events, session_limit=session_limit)

    def _job_record(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
    ) -> ConsoleRuntimeJobRecord | None:
        return (
            db.query(ConsoleRuntimeJobRecord)
            .filter(
                ConsoleRuntimeJobRecord.user_id == user_id,
                ConsoleRuntimeJobRecord.job_id == job_id,
            )
            .first()
        )

    def _required_job_record(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
    ) -> ConsoleRuntimeJobRecord:
        record = self._job_record(db, user_id=user_id, job_id=job_id)
        if record is None:
            raise JobNotFoundError(f"Unknown job: {job_id}")
        return record

    def _ensure_not_terminal(self, record: ConsoleRuntimeJobRecord) -> None:
        if record.status in _TERMINAL_STATES:
            raise InvalidTransitionError(
                f"Job {record.job_id} is already {record.status}"
            )

    def _record_artifacts(
        self, record: ConsoleRuntimeJobRecord, artifacts: Iterable[str]
    ) -> list[str]:
        current = _json_list(record.artifacts_json)
        added: list[str] = []
        for artifact in artifacts:
            value = _clean(artifact)
            if value and value not in current:
                current.append(value)
                added.append(value)
        if added:
            record.artifacts_json = current
        return added

    def _events_for_job(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
    ) -> list[ConsoleRuntimeEvent]:
        records = (
            db.query(ConsoleRuntimeEventRecord)
            .filter(
                ConsoleRuntimeEventRecord.user_id == user_id,
                ConsoleRuntimeEventRecord.job_id == job_id,
            )
            .order_by(ConsoleRuntimeEventRecord.sequence.asc())
            .all()
        )
        return [_to_event(record) for record in records]

    def _events_for_user(
        self,
        db: Session,
        *,
        user_id: int,
        limit: int = 1000,
    ) -> list[ConsoleRuntimeEvent]:
        records = (
            db.query(ConsoleRuntimeEventRecord)
            .filter(ConsoleRuntimeEventRecord.user_id == user_id)
            .order_by(ConsoleRuntimeEventRecord.sequence.desc())
            .limit(max(1, min(int(limit or 1000), 10000)))
            .all()
        )
        return [_to_event(record) for record in reversed(records)]

    def _append_event_record(
        self,
        db: Session,
        *,
        user_id: int,
        job_id: str,
        event_type: str,
        payload: dict[str, Any],
        summary: str = "",
        detail: str = "",
        visibility: str = "timeline",
        created_at: datetime | None = None,
    ) -> ConsoleRuntimeEventRecord:
        sequence = self._next_sequence(db)
        event = ConsoleRuntimeEvent(
            job_id=job_id,
            event_type=event_type,
            payload=payload,
            sequence=sequence,
            summary=summary,
            detail=detail,
            visibility=visibility,
            created_at=_iso(created_at or _utc_now()),
        )
        record = ConsoleRuntimeEventRecord(
            user_id=user_id,
            job_id=job_id,
            event_id=event.event_id,
            sequence=event.sequence,
            event_type=event.event_type,
            category=event.category,
            summary=event.summary,
            detail=event.detail,
            visibility=event.visibility,
            payload_json=event.payload,
            created_at=created_at or _utc_now(),
        )
        db.add(record)
        return record

    def _next_sequence(self, db: Session) -> int:
        current = db.query(func.max(ConsoleRuntimeEventRecord.sequence)).scalar()
        return int(current or 0) + 1


db_console_runtime_store = DbConsoleRuntimeStore()
