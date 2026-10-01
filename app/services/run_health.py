from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


RUN_HEALTH_SCHEMA = "norman.run-health.v1"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class RunHealthPolicy:
    window_events: int = 24
    repeated_prompt_warn: int = 3
    repeated_prompt_stop: int = 5
    consecutive_failures_warn: int = 3
    consecutive_failures_stop: int = 5
    deep_chain_depth: int = 8
    repaired_continuations_warn: int = 2
    exhausted_continuations_stop: int = 1
    token_window_warn: int = 100_000
    token_window_stop: int = 200_000

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if int(value) < 1:
                raise ValueError(f"RunHealthPolicy {name} must be positive")


def _maximum_count(values: Sequence[str]) -> int:
    counts = Counter(value for value in values if value)
    return max(counts.values(), default=0)


def _consecutive_failures(events: Sequence[Mapping[str, Any]]) -> int:
    count = 0
    for event in reversed(events):
        status = _clean(event.get("status")).lower()
        if status == "success":
            break
        if status:
            count += 1
    return count


def evaluate_proxy_run_health(
    events: Sequence[Mapping[str, Any]],
    *,
    policy: RunHealthPolicy | None = None,
) -> dict[str, Any]:
    """Classify bounded proxy evidence without retaining request content."""

    active_policy = policy or RunHealthPolicy()
    bounded = [
        dict(event)
        for event in events[-active_policy.window_events :]
        if isinstance(event, Mapping)
    ]
    latest_workflow = _clean(bounded[-1].get("workflow_sha256")) if bounded else ""
    window = [
        event
        for event in bounded
        if _clean(event.get("workflow_sha256")) == latest_workflow
    ]
    prompt_repeat = _maximum_count(
        [_clean(event.get("prompt_sha256")) for event in window]
    )
    request_shape_repeat = _maximum_count(
        [_clean(event.get("request_shape_sha256")) for event in window]
    )
    consecutive_failures = _consecutive_failures(window)
    token_total = sum(
        _int(_mapping(event.get("usage")).get("total_tokens")) for event in window
    )
    tool_chains = [_mapping(event.get("tool_chain")) for event in window]
    maximum_chain_depth = max(
        (_int(chain.get("chain_depth")) for chain in tool_chains), default=0
    )
    repaired = sum(
        _clean(chain.get("watchdog_state")) == "repaired" for chain in tool_chains
    )
    exhausted = sum(
        _clean(chain.get("watchdog_state")) == "exhausted" for chain in tool_chains
    )

    signals: list[dict[str, Any]] = []

    def signal(
        code: str,
        *,
        severity: str,
        observed: int,
        threshold: int,
        detail: str,
    ) -> None:
        signals.append(
            {
                "code": code,
                "severity": severity,
                "observed": observed,
                "threshold": threshold,
                "detail": detail,
            }
        )

    if prompt_repeat >= active_policy.repeated_prompt_stop:
        signal(
            "repeated_prompt_loop",
            severity="stop",
            observed=prompt_repeat,
            threshold=active_policy.repeated_prompt_stop,
            detail="The same prompt fingerprint repeated in the bounded window.",
        )
    elif prompt_repeat >= active_policy.repeated_prompt_warn:
        signal(
            "repeated_prompt_churn",
            severity="warn",
            observed=prompt_repeat,
            threshold=active_policy.repeated_prompt_warn,
            detail="A prompt fingerprint repeated unusually often.",
        )

    if consecutive_failures >= active_policy.consecutive_failures_stop:
        signal(
            "consecutive_failure_loop",
            severity="stop",
            observed=consecutive_failures,
            threshold=active_policy.consecutive_failures_stop,
            detail="The proxy has a sustained trailing failure streak.",
        )
    elif consecutive_failures >= active_policy.consecutive_failures_warn:
        signal(
            "consecutive_failure_churn",
            severity="warn",
            observed=consecutive_failures,
            threshold=active_policy.consecutive_failures_warn,
            detail="The proxy has multiple consecutive failures.",
        )

    if exhausted >= active_policy.exhausted_continuations_stop:
        signal(
            "tool_continuation_exhausted",
            severity="stop",
            observed=exhausted,
            threshold=active_policy.exhausted_continuations_stop,
            detail="A tool continuation remained invalid after bounded repair.",
        )
    elif repaired >= active_policy.repaired_continuations_warn:
        signal(
            "tool_continuation_repair_churn",
            severity="warn",
            observed=repaired,
            threshold=active_policy.repaired_continuations_warn,
            detail="Several tool continuations required repair.",
        )

    if maximum_chain_depth >= active_policy.deep_chain_depth:
        signal(
            "deep_tool_chain",
            severity="warn",
            observed=maximum_chain_depth,
            threshold=active_policy.deep_chain_depth,
            detail="A tool continuation exceeded the preferred chain depth.",
        )

    if token_total >= active_policy.token_window_stop:
        signal(
            "token_window_exhausted",
            severity="stop",
            observed=token_total,
            threshold=active_policy.token_window_stop,
            detail="The bounded proxy window consumed an excessive token volume.",
        )
    elif token_total >= active_policy.token_window_warn:
        signal(
            "token_window_pressure",
            severity="warn",
            observed=token_total,
            threshold=active_policy.token_window_warn,
            detail="The bounded proxy window has elevated token volume.",
        )

    state = (
        "stop"
        if any(item["severity"] == "stop" for item in signals)
        else ("warn" if signals else "normal")
    )
    return {
        "schema": RUN_HEALTH_SCHEMA,
        "state": state,
        "recommended_action": (
            "stop_and_checkpoint"
            if state == "stop"
            else ("inspect_and_reduce" if state == "warn" else "continue")
        ),
        "workflow_sha256": latest_workflow,
        "bounded_event_count": len(bounded),
        "window_event_count": len(window),
        "metrics": {
            "maximum_prompt_repeat": prompt_repeat,
            "maximum_request_shape_repeat": request_shape_repeat,
            "consecutive_failures": consecutive_failures,
            "maximum_chain_depth": maximum_chain_depth,
            "repaired_continuations": repaired,
            "exhausted_continuations": exhausted,
            "total_tokens": token_total,
        },
        "signals": signals,
        "policy": asdict(active_policy),
    }
