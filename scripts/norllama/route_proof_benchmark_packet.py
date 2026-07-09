#!/usr/bin/env python3
"""Generate a fresh Norllama route-proof benchmark packet from live probes."""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "norman.norllama.route-proof-benchmark-packet.v1"
DEFAULT_FRONTDOOR = "https://llm.home.arpa"
DEFAULT_OUTPUT = Path("/tmp/norllama_route_proof_benchmark_packet.json")
WORKER_BY_HOST = {
    "127.0.0.1": "mac-mini-133",
    "localhost": "mac-mini-133",
    "192.168.2.133": "mac-mini-133",
    "2.133": "mac-mini-133",
    "192.168.2.150": "spark-150",
    "2.150": "spark-150",
    "192.168.2.151": "spark-151",
    "2.151": "spark-151",
}


@dataclass(frozen=True)
class ProbeSpec:
    lane_id: str
    model: str
    profile: str
    prompt: str
    expected: str
    use_for: str
    guardrail: str
    timeout_seconds: float = 120.0
    capability_class: str = "chat"
    target_role: str = "production"
    max_tokens: int = 24


CHAT_PROBES: tuple[ProbeSpec, ...] = (
    ProbeSpec(
        lane_id="coder",
        model="qwen3.6:27b",
        profile="qwen36_27_local_route_proof",
        prompt=(
            "Norman route-proof benchmark. Reply exactly: " "NORMAN_QWEN36_27B_CODE_OK"
        ),
        expected="NORMAN_QWEN36_27B_CODE_OK",
        use_for=(
            "default local coding, repo reasoning, patch drafting, tool-call "
            "risk classification, and command drafting"
        ),
        guardrail="Run deterministic tests and receipt checks before authority.",
        timeout_seconds=120.0,
        capability_class="code",
    ),
    ProbeSpec(
        lane_id="planner",
        model="qwen3.6:35b-a3b-q4_K_M",
        profile="qwen36_35_router_local_route_proof",
        prompt=(
            "Norman route-proof benchmark. Reply exactly: "
            "NORMAN_QWEN36_35B_ROUTER_OK"
        ),
        expected="NORMAN_QWEN36_35B_ROUTER_OK",
        use_for=(
            "interactive local planning, routing, filtering, scout prep, "
            "evidence compression, and summaries"
        ),
        guardrail="Use as preflight/draft planner; verify risky actions.",
        timeout_seconds=120.0,
        capability_class="planner",
    ),
    ProbeSpec(
        lane_id="judge",
        model="qwen3.5:122b-a10b-q4_K_M",
        profile="qwen35_122_heavy_judge_route_proof",
        prompt=(
            "Norman route-proof benchmark. Reply exactly: "
            "NORMAN_QWEN35_122B_JUDGE_OK"
        ),
        expected="NORMAN_QWEN35_122B_JUDGE_OK",
        use_for=(
            "heavy local judge, verifier, regression review, and cloud "
            "escalation reduction"
        ),
        guardrail="Judge lane only; avoid interactive default routing unless warm.",
        timeout_seconds=240.0,
        capability_class="judge",
    ),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean(value: Any) -> str:
    return str(value or "").strip()


def worker_from_url(value: Any) -> str:
    raw = clean(value)
    if not raw:
        return ""
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        return ""
    host = (parsed.hostname or raw).strip("[]").lower()
    return WORKER_BY_HOST.get(host, "")


def output_shape_for_text(
    text: str, *, timeout: bool = False, error: bool = False
) -> str:
    if timeout:
        return "timeout"
    if error:
        return "error"
    stripped = text.strip()
    if not stripped:
        return "empty"
    lowered = stripped.lower()
    progress_markers = (
        "i will",
        "i'll",
        "working on",
        "starting",
        "plan:",
        "next i",
    )
    if any(lowered.startswith(marker) for marker in progress_markers):
        return "progress_only"
    return "complete"


def json_request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = 30.0,
    verify_tls: bool = False,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "norman-route-proof-benchmark/1.0",
        },
    )
    context = None if verify_tls else ssl._create_unverified_context()
    with urllib.request.urlopen(
        request, timeout=timeout_seconds, context=context
    ) as response:
        data = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(data)
    return parsed if isinstance(parsed, dict) else {}


def usage_tokens(payload: dict[str, Any]) -> tuple[int, int, int]:
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}

    def as_int(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    input_tokens = as_int(usage.get("prompt_tokens") or usage.get("input_tokens"))
    output_tokens = as_int(usage.get("completion_tokens") or usage.get("output_tokens"))
    total_tokens = as_int(usage.get("total_tokens"))
    if not total_tokens:
        total_tokens = input_tokens + output_tokens
    return input_tokens, output_tokens, total_tokens


def chat_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    first = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    return clean(message.get("content") or first.get("text"))


def route_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    meta = payload.get("norllama")
    return meta if isinstance(meta, dict) else {}


def row_from_probe(
    *,
    spec: ProbeSpec,
    payload: dict[str, Any] | None,
    elapsed_ms: int,
    error: str = "",
    timed_out: bool = False,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    text = chat_text(payload)
    input_tokens, output_tokens, total_tokens = usage_tokens(payload)
    route = route_metadata(payload)
    upstream = clean(route.get("upstream"))
    worker = worker_from_url(upstream) or worker_from_url(
        (route.get("attempts") or [""])[-1]
        if isinstance(route.get("attempts"), list)
        else ""
    )
    output_shape = clean(route.get("output_shape")) or output_shape_for_text(
        text, timeout=timed_out, error=bool(error)
    )
    matched = bool(spec.expected and spec.expected in text)
    accepted = bool(
        matched
        and output_shape == "complete"
        and total_tokens > 0
        and not error
        and not timed_out
    )
    timeout_count = 1 if timed_out else 0
    empty_count = 1 if not text.strip() and not timed_out else 0
    zero_token_count = 1 if not total_tokens and not timed_out else 0
    progress_count = 1 if output_shape == "progress_only" else 0
    verifier_rejection_count = 0 if accepted else 1
    score = 0.95 if accepted else 0.0
    if accepted and elapsed_ms > spec.timeout_seconds * 750:
        score = 0.72
    elif accepted and elapsed_ms > spec.timeout_seconds * 500:
        score = 0.82
    return {
        "lane_id": spec.lane_id,
        "model": clean(payload.get("model")) or spec.model,
        "profile": spec.profile,
        "priority": "p1" if spec.lane_id == "judge" else "p0",
        "capability_class": spec.capability_class,
        "use_for": spec.use_for,
        "guardrail": spec.guardrail,
        "target_worker": worker,
        "target_role": spec.target_role,
        "status": "benchmark_backed" if accepted else "failed",
        "benchmark_status": "benchmark_backed" if accepted else "failed",
        "score": score,
        "coverage_ratio": 1.0,
        "accepted_count": 1 if accepted else 0,
        "total_count": 1,
        "timeout_count": timeout_count,
        "timeout_rate": timeout_count,
        "empty_response_count": empty_count,
        "empty_response_rate": empty_count,
        "zero_token_count": zero_token_count,
        "zero_token_rate": zero_token_count,
        "progress_only_count": progress_count,
        "progress_only_rate": progress_count,
        "verifier_rejection_count": verifier_rejection_count,
        "verifier_rejection_rate": verifier_rejection_count,
        "output_shape_valid": output_shape == "complete",
        "output_shape": output_shape,
        "cold_start_p95": elapsed_ms,
        "warm_latency_p95": elapsed_ms,
        "completion_ms": elapsed_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "usage_bucket": "offline_local",
        "selected_provider": "norllama",
        "cloud_proxy": False,
        "frontdoor": DEFAULT_FRONTDOOR,
        "upstream": upstream,
        "observed_worker": worker,
        "expected": spec.expected,
        "matched_expected": matched,
        "error": error[:240],
    }


def run_chat_probe(
    spec: ProbeSpec,
    *,
    frontdoor: str,
    verify_tls: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        payload = json_request(
            "POST",
            f"{frontdoor.rstrip('/')}/v1/chat/completions",
            payload={
                "model": spec.model,
                "messages": [{"role": "user", "content": spec.prompt}],
                "temperature": 0,
                "max_tokens": spec.max_tokens,
            },
            timeout_seconds=spec.timeout_seconds,
            verify_tls=verify_tls,
        )
        return row_from_probe(
            spec=spec,
            payload=payload,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
    except (TimeoutError, socket.timeout) as exc:
        return row_from_probe(
            spec=spec,
            payload={},
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            error=str(exc),
            timed_out=True,
        )
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        return row_from_probe(
            spec=spec,
            payload={},
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            error=str(exc),
        )


def summarize_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    accepted = sum(int(row.get("accepted_count") or 0) for row in rows)
    timeouts = sum(int(row.get("timeout_count") or 0) for row in rows)
    empty = sum(int(row.get("empty_response_count") or 0) for row in rows)
    zero = sum(int(row.get("zero_token_count") or 0) for row in rows)
    progress = sum(int(row.get("progress_only_count") or 0) for row in rows)
    return {
        "row_count": total,
        "accepted_count": accepted,
        "timeout_count": timeouts,
        "empty_response_count": empty,
        "zero_token_count": zero,
        "progress_only_count": progress,
        "accepted_ratio": round(accepted / total, 4) if total else 0.0,
        "timeout_rate": round(timeouts / total, 4) if total else 0.0,
    }


def capability_contracts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_lane = {clean(row.get("lane_id")): row for row in rows}
    contracts: list[dict[str, Any]] = []

    def add(
        contract_id: str,
        row: dict[str, Any] | None,
        *,
        title: str,
        dispatch: str = "unified_chat",
        aliases: list[str] | None = None,
    ) -> None:
        if not row:
            return
        contracts.append(
            {
                "contract_id": contract_id,
                "title": title,
                "aliases": aliases or [],
                "default_model": row.get("model"),
                "default_profile": row.get("profile"),
                "dispatch": dispatch,
                "status": row.get("benchmark_status"),
                "benchmark_confidence": "high"
                if row.get("accepted_count")
                else "failed",
                "selection_method": "uplink_route_proof_live_probe",
                "best_weighted_score": row.get("score"),
                "target_worker": row.get("target_worker"),
                "target_role": row.get("target_role"),
                "accepted_count": row.get("accepted_count"),
                "total_count": row.get("total_count"),
                "timeout_rate": row.get("timeout_rate"),
                "empty_response_rate": row.get("empty_response_rate"),
                "zero_token_rate": row.get("zero_token_rate"),
                "progress_only_rate": row.get("progress_only_rate"),
                "output_shape_valid": row.get("output_shape_valid"),
                "guardrail": row.get("guardrail"),
            }
        )

    add(
        "chat",
        by_lane.get("planner"),
        title="Interactive local chat, planning, routing, and summaries",
        aliases=["general_chat", "default"],
    )
    add(
        "code_risk",
        by_lane.get("coder"),
        title="Local coding, patch risk, and deterministic-tool preflight",
        aliases=["patch_risk", "test_selection", "change_impact"],
    )
    add(
        "judge",
        by_lane.get("judge"),
        title="Heavy local verification and escalation reduction",
        aliases=["verifier", "heavyweight_judge"],
    )
    return contracts


def build_packet(
    *,
    rows: list[dict[str, Any]],
    frontdoor: str,
    generated_at: str | None = None,
    packet_id: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or utc_now()
    packet_id = (
        packet_id
        or f"uplink-route-proof-{generated_at.replace(':', '').replace('-', '')}"
    )
    rows = [dict(row, frontdoor=frontdoor.rstrip("/")) for row in rows]
    return {
        "schema": SCHEMA,
        "packet_id": packet_id,
        "id": packet_id,
        "generated_at": generated_at,
        "source": {
            "kind": "live_route_proof_probe",
            "frontdoor": frontdoor.rstrip("/"),
            "selection_method": "uplink_route_proof_live_probe",
        },
        "aggregate": summarize_counts(rows),
        "shareable_view": {
            "recommended_roles": rows,
            "benchmark_results": rows,
        },
        "benchmark_results": rows,
        "capability_contracts": capability_contracts(rows),
    }


def write_packet(
    packet: dict[str, Any],
    output: Path,
    *,
    backup_existing: bool = False,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    if backup_existing and output.exists():
        stamp = utc_now().replace(":", "").replace("-", "")
        backup = output.with_suffix(output.suffix + f".{stamp}.bak")
        backup.write_bytes(output.read_bytes())
    output.write_text(
        json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontdoor", default=DEFAULT_FRONTDOOR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-tls", action="store_true")
    parser.add_argument("--backup-existing", action="store_true")
    parser.add_argument(
        "--skip-heavy-judge",
        action="store_true",
        help="Skip the 122B judge probe when doing a quick refresh.",
    )
    parser.add_argument(
        "--allow-failures",
        action="store_true",
        help="Write a packet even if one or more probes fail.",
    )
    parser.add_argument("--packet-id", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    specs = [
        spec
        for spec in CHAT_PROBES
        if not (args.skip_heavy_judge and spec.lane_id == "judge")
    ]
    rows = [
        run_chat_probe(
            spec,
            frontdoor=args.frontdoor.rstrip("/"),
            verify_tls=bool(args.verify_tls),
        )
        for spec in specs
    ]
    packet = build_packet(
        rows=rows,
        frontdoor=args.frontdoor.rstrip("/"),
        packet_id=args.packet_id or f"uplink-route-proof-{uuid.uuid4().hex[:12]}",
    )
    write_packet(packet, args.output, backup_existing=bool(args.backup_existing))
    print(
        json.dumps(
            {
                "output": str(args.output),
                "aggregate": packet["aggregate"],
                "packet_id": packet["packet_id"],
            },
            indent=2,
        )
    )
    failed = [row for row in rows if not row.get("accepted_count")]
    if failed and not args.allow_failures:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
