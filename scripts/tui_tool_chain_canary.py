#!/usr/bin/env python3
"""Exercise the authenticated Responses tool continuation without real tools."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


SCHEMA = "norman.tui.tool-chain-canary.v2"
DEFAULT_ENDPOINT = "http://127.0.0.1:8000/v1/responses"
DEFAULT_OUTPUT_JSON = Path(
    "/home/kristopher/.local/state/norman/tui-tool-chain-canary.json"
)
DEFAULT_PRESSURE_GUARD = Path(__file__).with_name("tui_host_pressure_guard.py")
DEFAULT_PRESSURE_TARGET = "work-special"
DEFAULT_TIMEOUT_SECONDS = 45.0
KNOWN_TOOL_NAMES = frozenset({"tool_search", "mcp__norman_canary__status_lookup"})
SAFE_TOOL_CHAIN_SCHEMA = "norman.responses-tool-chain.v1"
SAFE_TOOL_CHAIN_TURN_TYPES = frozenset({"after_tool_result", "initial_or_text"})
SAFE_TOOL_CHAIN_OUTCOMES = frozenset(
    {
        "final_after_tool",
        "final_without_tool",
        "invalid_or_unresolved",
        "tool_call",
    }
)
SAFE_WATCHDOG_STATES = frozenset({"normal", "passthrough", "repaired", "exhausted"})
SAFE_BRIDGE_MODES = frozenset({"transparent", "governed"})
SAFE_TOOL_TRANSPORTS = frozenset({"local_text_adapter"})
SAFE_STATE_RETENTIONS = frozenset({"ephemeral", "session"})

RequestFn = Callable[[str, dict[str, Any], str, float], tuple[int, dict[str, Any]]]
StreamRequestFn = Callable[
    [str, dict[str, Any], str, float], tuple[int, dict[str, Any]]
]
PressureGuardFn = Callable[[], dict[str, Any]]
RAW_TOOL_ENVELOPE_PATTERN = re.compile(r'\{\s*"tool_calls?"\s*:')


class CanaryError(RuntimeError):
    def __init__(self, kind: str, *, http_status: int = 0) -> None:
        super().__init__(kind)
        self.kind = kind
        self.http_status = max(0, int(http_status or 0))


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _bounded_int(value: Any, *, maximum: int = 1_000_000) -> int:
    return min(_int(value), maximum)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_identifier(value: Any, *, maximum: int = 192) -> str:
    candidate = _clean(value)
    if not candidate:
        return ""
    allowed = frozenset(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:/@+-"
    )
    if any(character not in allowed for character in candidate):
        return "unknown"
    return candidate[:maximum]


def _is_raw_tool_payload_text(value: Any) -> bool:
    text = _clean(value)
    if RAW_TOOL_ENVELOPE_PATTERN.search(text):
        return True
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return False
    return (
        isinstance(payload, Mapping)
        and _clean(payload.get("type")) == "function_call"
        and bool(_clean(payload.get("name")))
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_timeout(value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    return min(120.0, max(1.0, timeout))


def _post_json(
    endpoint: str,
    payload: dict[str, Any],
    token: str,
    timeout_seconds: float,
) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Norman-Gateway-Route": "norman",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(getattr(response, "status", 200) or 200)
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise CanaryError("http_error", http_status=exc.code) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise CanaryError("transport_error") from exc
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise CanaryError("invalid_json", http_status=status) from exc
    if not isinstance(parsed, dict):
        raise CanaryError("invalid_response_shape", http_status=status)
    if status != 200:
        raise CanaryError("unexpected_http_status", http_status=status)
    return status, parsed


def _parse_sse_events(raw: str) -> list[dict[str, Any]]:
    """Parse a complete SSE body into event names and JSON payloads."""

    return _parse_sse_event_lines(raw.splitlines())


def _parse_sse_event_lines(
    lines: Any,
    *,
    started_at: float | None = None,
) -> list[dict[str, Any]]:
    """Parse SSE lines and retain local arrival timing when available."""

    events: list[dict[str, Any]] = []
    event_name = ""
    data_lines: list[str] = []

    def finish_event() -> None:
        nonlocal event_name, data_lines
        if not data_lines:
            event_name = ""
            return
        data = "\n".join(data_lines)
        if data == "[DONE]":
            event: dict[str, Any] = {"event": event_name, "data": "[DONE]"}
        else:
            try:
                payload = json.loads(data)
            except json.JSONDecodeError as exc:
                raise CanaryError("invalid_sse_event") from exc
            if not isinstance(payload, Mapping):
                raise CanaryError("invalid_sse_event")
            event = {"event": event_name, "data": dict(payload)}
        if started_at is not None:
            event["_received_ms"] = round(
                max(0.0, (time.monotonic() - started_at) * 1000.0),
                3,
            )
        events.append(event)
        event_name = ""
        data_lines = []

    for raw_line in lines:
        line = (
            raw_line.decode("utf-8", errors="replace")
            if isinstance(raw_line, bytes)
            else str(raw_line)
        ).rstrip("\r\n")
        if not line:
            finish_event()
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if not separator:
            continue
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event_name = value
        elif field == "data":
            data_lines.append(value)
    finish_event()
    return events


def _stream_timing(events: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = [
        float(event["_received_ms"])
        for event in events
        if isinstance(event.get("_received_ms"), (int, float))
    ]
    if not timestamps:
        return {}

    cloud_heartbeat_times: list[float] = []
    local_stream_open_heartbeat_times: list[float] = []
    cloud_progress_count = 0
    local_stream_open_progress_count = 0
    for event in events:
        data = _mapping(event.get("data"))
        if _clean(data.get("type")) != "response.in_progress":
            continue
        norman = _mapping(_mapping(data.get("response")).get("norman"))
        metadata = _mapping(norman.get("cloud_fallback"))
        if not metadata:
            metadata = _mapping(norman.get("explicit_cloud_selection"))
        if not metadata:
            metadata = _mapping(norman.get("local_stream_open"))
            if metadata:
                local_stream_open_progress_count += 1
                if bool(metadata.get("heartbeat")) and isinstance(
                    event.get("_received_ms"), (int, float)
                ):
                    local_stream_open_heartbeat_times.append(
                        float(event["_received_ms"])
                    )
            continue
        cloud_progress_count += 1
        if bool(metadata.get("heartbeat")) and isinstance(
            event.get("_received_ms"), (int, float)
        ):
            cloud_heartbeat_times.append(float(event["_received_ms"]))

    gaps = [current - previous for previous, current in zip(timestamps, timestamps[1:])]
    timing: dict[str, Any] = {
        "event_count": len(timestamps),
        "time_to_first_event_ms": round(timestamps[0], 3),
        "max_inter_event_gap_ms": round(max(gaps, default=0.0), 3),
        "cloud_progress_count": cloud_progress_count,
        "cloud_heartbeat_count": len(cloud_heartbeat_times),
        "local_stream_open_progress_count": local_stream_open_progress_count,
        "local_stream_open_heartbeat_count": len(local_stream_open_heartbeat_times),
    }
    if cloud_heartbeat_times:
        timing["first_cloud_heartbeat_ms"] = round(cloud_heartbeat_times[0], 3)
        timing["last_cloud_heartbeat_ms"] = round(cloud_heartbeat_times[-1], 3)
    if local_stream_open_heartbeat_times:
        timing["first_local_stream_open_heartbeat_ms"] = round(
            local_stream_open_heartbeat_times[0],
            3,
        )
        timing["last_local_stream_open_heartbeat_ms"] = round(
            local_stream_open_heartbeat_times[-1],
            3,
        )
    return timing


def _stream_response_from_sse_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Retain only the completion response plus protocol-safe stream metadata."""

    completed_response: dict[str, Any] = {}
    native_calls: list[dict[str, str]] = []
    saw_completion = False
    saw_done = False
    saw_failure = False
    failure_code = ""
    raw_tool_envelope_text = False

    for event in events:
        data = event.get("data")
        if data == "[DONE]":
            saw_done = True
            continue
        payload = _mapping(data)
        event_type = _clean(payload.get("type")) or _clean(event.get("event"))
        if event_type == "response.output_item.added":
            item = _mapping(payload.get("item"))
            if _clean(item.get("type")) == "function_call":
                native_calls.append(
                    {
                        "name": _clean(item.get("name")),
                        "call_id": _clean(item.get("call_id")),
                    }
                )
        elif event_type == "response.output_text.delta":
            if _is_raw_tool_payload_text(payload.get("delta")):
                raw_tool_envelope_text = True
        elif event_type == "response.completed":
            completed_response = _mapping(payload.get("response"))
            saw_completion = True
        elif event_type in {"response.failed", "error"}:
            saw_failure = True
            failed_response = _mapping(payload.get("response"))
            failure_code = _safe_identifier(
                _mapping(failed_response.get("error")).get("code")
                or _mapping(payload.get("error")).get("code"),
                maximum=96,
            )

    if _is_raw_tool_payload_text(completed_response.get("output_text")):
        raw_tool_envelope_text = True
    completed_response["_canary_stream"] = {
        "completed": saw_completion,
        "done": saw_done,
        "failed": saw_failure,
        "failure_code": failure_code,
        "native_function_calls": native_calls,
        "raw_tool_envelope_text": raw_tool_envelope_text,
    }
    timing = _stream_timing(events)
    if timing:
        completed_response["_canary_stream"]["timing"] = timing
    return completed_response


def _post_sse(
    endpoint: str,
    payload: dict[str, Any],
    token: str,
    timeout_seconds: float,
) -> tuple[int, dict[str, Any]]:
    started_at = time.monotonic()
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Norman-Gateway-Route": "norman",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(getattr(response, "status", 200) or 200)
            events = _parse_sse_event_lines(response, started_at=started_at)
    except urllib.error.HTTPError as exc:
        raise CanaryError("http_error", http_status=exc.code) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise CanaryError("transport_error") from exc
    if status != 200:
        raise CanaryError("unexpected_http_status", http_status=status)
    return status, _stream_response_from_sse_events(events)


def _pressure_guard(
    script_path: Path,
    *,
    target: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--target",
                target,
                "--json",
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _safe_tool_chain(response: Mapping[str, Any]) -> dict[str, Any]:
    norman = _mapping(response.get("norman"))
    compatibility = _mapping(norman.get("responses_compatibility"))
    tool_chain = _mapping(compatibility.get("tool_chain"))
    if _clean(tool_chain.get("schema")) != SAFE_TOOL_CHAIN_SCHEMA:
        return {}
    watchdog = _mapping(tool_chain.get("watchdog"))
    turn_type = _clean(tool_chain.get("turn_type"))
    outcome = _clean(tool_chain.get("outcome"))
    watchdog_state = _clean(watchdog.get("state"))
    return {
        "schema": SAFE_TOOL_CHAIN_SCHEMA,
        "turn_type": (
            turn_type if turn_type in SAFE_TOOL_CHAIN_TURN_TYPES else "unknown"
        ),
        "chain_depth": _int(tool_chain.get("chain_depth")),
        "tool_results_supplied": _int(tool_chain.get("tool_results_supplied")),
        "tool_results_matched": _int(tool_chain.get("tool_results_matched")),
        "tool_calls_returned": _int(tool_chain.get("tool_calls_returned")),
        "outcome": outcome if outcome in SAFE_TOOL_CHAIN_OUTCOMES else "unknown",
        "watchdog_state": (
            watchdog_state if watchdog_state in SAFE_WATCHDOG_STATES else "unknown"
        ),
        "watchdog_attempts": _int(watchdog.get("attempts")),
    }


def _safe_bridge_receipt(response: Mapping[str, Any]) -> dict[str, Any]:
    """Keep a route receipt useful for operators without writing response content."""

    norman = _mapping(response.get("norman"))
    compatibility = _mapping(norman.get("responses_compatibility"))
    budget = _mapping(norman.get("output_token_budget"))
    if not compatibility and not budget:
        return {}
    route = _mapping(norman.get("route"))
    fallback = _mapping(norman.get("cloud_fallback"))
    bridge_mode = _clean(compatibility.get("tool_bridge_mode"))
    tool_transport = _clean(compatibility.get("tool_transport"))
    state_retention = _clean(compatibility.get("state_retention"))
    return {
        "mode": bridge_mode if bridge_mode in SAFE_BRIDGE_MODES else "unknown",
        "tool_transport": (
            tool_transport if tool_transport in SAFE_TOOL_TRANSPORTS else "unknown"
        ),
        "state_retention": (
            state_retention if state_retention in SAFE_STATE_RETENTIONS else "unknown"
        ),
        "effective_backend": {
            "provider": _safe_identifier(
                route.get("selected_provider") or fallback.get("fallback_provider")
            )
            or "unknown",
            "model": _safe_identifier(
                route.get("selected_model")
                or response.get("model")
                or fallback.get("fallback_model")
            )
            or "unknown",
        },
        "output_token_budget": {
            "requested": _bounded_int(budget.get("requested")),
            "effective": _bounded_int(budget.get("effective")),
            "maximum": _bounded_int(budget.get("maximum")),
        },
        "fallback_reason": _safe_identifier(
            fallback.get("local_failure_code"), maximum=96
        ),
    }


def _function_calls(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    output = response.get("output")
    if not isinstance(output, list):
        return []
    return [
        dict(item)
        for item in output
        if isinstance(item, Mapping) and _clean(item.get("type")) == "function_call"
    ]


def _safe_tool_name(value: Any) -> str:
    name = _clean(value)
    return name if name in KNOWN_TOOL_NAMES else "unexpected"


def _turn_receipt(
    *,
    turn: str,
    status: int,
    elapsed_ms: float,
    response: Mapping[str, Any],
) -> dict[str, Any]:
    output = response.get("output")
    output_count = len(output) if isinstance(output, list) else 0
    calls = _function_calls(response)
    stream = _mapping(response.get("_canary_stream"))
    stream_calls = stream.get("native_function_calls")
    native_calls = (
        [dict(call) for call in stream_calls if isinstance(call, Mapping)]
        if isinstance(stream_calls, list)
        else []
    )
    stream_receipt = {
        "completed": bool(stream.get("completed")),
        "done": bool(stream.get("done")),
        "failed": bool(stream.get("failed")),
        "native_function_call_count": len(native_calls),
        "native_tool_names": [
            _safe_tool_name(call.get("name")) for call in native_calls
        ],
        "raw_tool_envelope_text": bool(stream.get("raw_tool_envelope_text")),
    }
    failure_code = _safe_identifier(stream.get("failure_code"), maximum=96)
    if failure_code:
        stream_receipt["failure_code"] = failure_code
    timing = _mapping(stream.get("timing"))
    if timing:
        stream_receipt["timing"] = timing
    return {
        "turn": turn,
        "http_status": int(status),
        "elapsed_ms": round(elapsed_ms, 3),
        "response_id": _clean(response.get("id")),
        "status": _clean(response.get("status")) or "unknown",
        "output_count": output_count,
        "function_call_count": len(calls),
        "tool_names": [_safe_tool_name(call.get("name")) for call in calls],
        "tool_chain": _safe_tool_chain(response),
        "bridge": _safe_bridge_receipt(response),
        "stream": stream_receipt if stream else {},
    }


def _require_stream_integrity(response: Mapping[str, Any]) -> None:
    stream = _mapping(response.get("_canary_stream"))
    if not stream:
        raise CanaryError("missing_stream_metadata")
    if bool(stream.get("failed")):
        raise CanaryError("stream_failed")
    if not bool(stream.get("completed")):
        raise CanaryError("missing_stream_completion")
    if not bool(stream.get("done")):
        raise CanaryError("missing_stream_done")
    if bool(stream.get("raw_tool_envelope_text")):
        raise CanaryError("raw_tool_envelope_text")


def _require_exact_function_call(
    response: Mapping[str, Any],
    *,
    name: str,
    streaming: bool = False,
) -> str:
    if streaming:
        _require_stream_integrity(response)
        stream = _mapping(response.get("_canary_stream"))
        native_calls = stream.get("native_function_calls")
        if (
            not isinstance(native_calls, list)
            or len(native_calls) != 1
            or _clean(_mapping(native_calls[0]).get("name")) != name
        ):
            raise CanaryError("missing_native_function_event")
    output = response.get("output")
    calls = _function_calls(response)
    if (
        not isinstance(output, list)
        or len(calls) != 1
        or _clean(calls[0].get("name")) != name
    ):
        raise CanaryError("unexpected_function_call")
    call_id = _clean(calls[0].get("call_id"))
    if not call_id:
        raise CanaryError("missing_function_call_id")
    return call_id


def _require_final_answer(
    response: Mapping[str, Any], *, streaming: bool = False
) -> None:
    if streaming:
        _require_stream_integrity(response)
    if _function_calls(response) or not _clean(response.get("output_text")):
        raise CanaryError("unexpected_final_response")


def _tool_search_definition() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "tool_search",
        "description": "Discover the next executable tool.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }


def _synthetic_status_definition() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "status_lookup",
        "description": "Return a synthetic canary status.",
        "parameters": {"type": "object", "properties": {}},
    }


def _synthetic_status_namespace() -> dict[str, Any]:
    return {
        "type": "namespace",
        "name": "mcp__norman_canary",
        "tools": [_synthetic_status_definition()],
    }


def _canary_prompt() -> str:
    return (
        "Run the Norman tool-chain health check. First call tool_search to discover "
        "mcp__norman_canary__status_lookup. After its synthetic result is supplied, "
        "call mcp__norman_canary__status_lookup. Do not call any real MCP or "
        "external tool."
    )


def run_canary(
    *,
    endpoint: str,
    token: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    pressure_guard: PressureGuardFn | None = None,
    request_fn: RequestFn = _post_json,
    streaming: bool = False,
    stream_request_fn: StreamRequestFn = _post_sse,
) -> dict[str, Any]:
    started_at = time.monotonic()
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "checked_at": _now(),
        "endpoint": endpoint,
        "gateway_route": "norman",
        "model": "norman-code",
        "mode": "streaming" if streaming else "non_streaming",
        "state": "failed",
        "elapsed_ms": 0.0,
        "turns": [],
    }
    pressure_state = _mapping((pressure_guard or (lambda: {}))())
    admission = _mapping(pressure_state.get("admission"))
    action = _clean(admission.get("action"))
    if action == "block_new_work":
        receipt.update(
            state="skipped",
            skip_reason="host_pressure",
            pressure_admission=action,
            elapsed_ms=round((time.monotonic() - started_at) * 1000.0, 3),
        )
        return receipt
    if not _clean(token):
        receipt.update(
            failure_kind="token_unavailable",
            elapsed_ms=round((time.monotonic() - started_at) * 1000.0, 3),
        )
        return receipt

    def execute_turn(turn: str, payload: dict[str, Any]) -> dict[str, Any]:
        turn_started_at = time.monotonic()
        payload = dict(payload)
        if streaming:
            payload["stream"] = True
        execute_request = stream_request_fn if streaming else request_fn
        status, response = execute_request(
            endpoint,
            payload,
            token,
            _bounded_timeout(timeout_seconds),
        )
        turn_receipt = _turn_receipt(
            turn=turn,
            status=status,
            elapsed_ms=(time.monotonic() - turn_started_at) * 1000.0,
            response=response,
        )
        receipt["turns"].append(turn_receipt)
        if turn_receipt["bridge"]:
            receipt["bridge"] = turn_receipt["bridge"]
        return response

    try:
        discovery = execute_turn(
            "tool_search",
            {
                "model": "norman-code",
                "input": _canary_prompt(),
                "tools": [_tool_search_definition()],
            },
        )
        tool_search_call_id = _require_exact_function_call(
            discovery,
            name="tool_search",
            streaming=streaming,
        )
        tool_call = execute_turn(
            "synthetic_status_lookup",
            {
                "model": "norman-code",
                "previous_response_id": _clean(discovery.get("id")),
                "input": [
                    {
                        "type": "function_call_output",
                        "call_id": tool_search_call_id,
                        "output": (
                            '{"tools":[{"name":"mcp__norman_canary__status_lookup",'
                            '"description":"Synthetic canary status lookup"}]}'
                        ),
                    }
                ],
                "tools": [_synthetic_status_namespace()],
            },
        )
        synthetic_call_id = _require_exact_function_call(
            tool_call,
            name="mcp__norman_canary__status_lookup",
            streaming=streaming,
        )
        final = execute_turn(
            "final_answer",
            {
                "model": "norman-code",
                "previous_response_id": _clean(tool_call.get("id")),
                "input": [
                    {
                        "type": "function_call_output",
                        "call_id": synthetic_call_id,
                        "output": '{"status":"ok","source":"synthetic"}',
                    },
                    {
                        "type": "message",
                        "role": "user",
                        "content": (
                            "The synthetic result has been supplied. Return a "
                            "concise final health result now. Do not call another tool."
                        ),
                    },
                ],
                "tools": [_synthetic_status_namespace()],
            },
        )
        _require_final_answer(final, streaming=streaming)
    except CanaryError as exc:
        receipt["failure_kind"] = exc.kind
        if exc.http_status:
            receipt["failure_http_status"] = exc.http_status
    except Exception:
        receipt["failure_kind"] = "unexpected_error"
    else:
        receipt["state"] = "passed"
    receipt["elapsed_ms"] = round((time.monotonic() - started_at) * 1000.0, 3)
    return receipt


def write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)
        json.dump(dict(receipt), handle, indent=2, sort_keys=True)
        handle.write("\n")
    temporary_path.replace(path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a synthetic authenticated Norman Responses tool-chain canary."
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get(
            "NORMAN_TUI_TOOL_CHAIN_CANARY_ENDPOINT", DEFAULT_ENDPOINT
        ),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path(
            os.environ.get(
                "NORMAN_TUI_TOOL_CHAIN_CANARY_OUTPUT_JSON",
                str(DEFAULT_OUTPUT_JSON),
            )
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--pressure-guard",
        type=Path,
        default=DEFAULT_PRESSURE_GUARD,
    )
    parser.add_argument("--pressure-target", default=DEFAULT_PRESSURE_TARGET)
    parser.add_argument("--skip-pressure-guard", action="store_true")
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Exercise the SSE streaming path used by Codex TUIs.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    def skip_pressure_guard() -> dict[str, Any]:
        return {}

    def configured_pressure_guard() -> dict[str, Any]:
        return _pressure_guard(
            args.pressure_guard,
            target=_clean(args.pressure_target) or DEFAULT_PRESSURE_TARGET,
            timeout_seconds=min(30.0, _bounded_timeout(args.timeout_seconds)),
        )

    pressure_guard: PressureGuardFn
    if args.skip_pressure_guard:
        pressure_guard = skip_pressure_guard
    else:
        pressure_guard = configured_pressure_guard
    receipt = run_canary(
        endpoint=_clean(args.endpoint) or DEFAULT_ENDPOINT,
        token=_clean(os.environ.get("NORMAN_PROMPT_PROXY_TOKEN")),
        timeout_seconds=args.timeout_seconds,
        pressure_guard=pressure_guard,
        streaming=bool(args.stream),
    )
    write_receipt(args.output_json, receipt)
    print(
        "tui-tool-chain-canary: state={state} turns={turns}".format(
            state=receipt["state"],
            turns=len(receipt["turns"]),
        )
    )
    return 0 if receipt["state"] in {"passed", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
