#!/usr/bin/env python3
"""Non-disruptive Norllama degraded-estate release matrix.

This script records what the live estate proves without pretending that node
outage drills happened. Destructive scenarios are marked ``not_exercised``
unless an operator supplies an external evidence file from an outage drill.
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "norman.norllama.degraded-estate-matrix.v1"
DEFAULT_FRONTDOOR = "https://llm.home.arpa"
DESTRUCTIVE_SCENARIOS = {
    "spark_151_unavailable",
    "spark_150_unavailable",
    "both_sparks_unavailable_2_133_available",
    "all_local_inference_unavailable",
    "explicit_cloud_escalation",
    "stale_benchmark_packet",
    "policy_refresh_failure",
    "worker_substitution",
}


@dataclass(frozen=True)
class HttpCapture:
    status: int
    payload: dict[str, Any]
    error: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean(value: Any) -> str:
    return str(value or "").strip()


def http_get_json(url: str, *, timeout_seconds: float = 20.0) -> HttpCapture:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "norman-degraded-estate-matrix/1.0"},
        method="GET",
    )
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(
            request, timeout=timeout_seconds, context=context
        ) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw.strip() else {}
            return HttpCapture(
                status=int(response.status),
                payload=parsed if isinstance(parsed, dict) else {},
            )
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            parsed = {}
        return HttpCapture(
            status=int(exc.code),
            payload=parsed if isinstance(parsed, dict) else {},
            error=raw.strip(),
        )
    except Exception as exc:  # pragma: no cover - live network guard
        return HttpCapture(status=0, payload={}, error=f"{type(exc).__name__}: {exc}")


def load_json(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text())
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return parsed


def live_snapshots(frontdoor: str) -> dict[str, dict[str, Any]]:
    base = frontdoor.rstrip("/")
    endpoints = {
        "readyz": "/readyz",
        "overview": "/v1/overview",
        "models": "/v1/models",
        "warm_policy": "/v1/warm-policy",
        "prefetch_status": "/v1/prefetch/status",
        "activity_execution": "/v1/activity?class=execution&limit=160",
    }
    snapshots: dict[str, dict[str, Any]] = {}
    for name, path in endpoints.items():
        capture = http_get_json(base + path)
        snapshots[name] = {
            "http_status": capture.status,
            "payload": capture.payload,
            "error": capture.error,
        }
    return snapshots


def fixture_snapshots(root: Path) -> dict[str, dict[str, Any]]:
    mapping = {
        "readyz": "llm-readyz.json",
        "overview": "llm-overview.json",
        "models": "llm-models.json",
        "warm_policy": "llm-warm-policy.json",
        "prefetch_status": "llm-prefetch-status.json",
        "activity_execution": "llm-activity-execution.json",
    }
    snapshots: dict[str, dict[str, Any]] = {}
    for key, filename in mapping.items():
        path = root / filename
        payload = load_json(path) if path.exists() else {}
        snapshots[key] = {
            "http_status": 200 if payload else 0,
            "payload": payload,
            "error": "" if payload else f"missing:{filename}",
        }
    return snapshots


def payload(snapshots: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    value = snapshots.get(key, {}).get("payload")
    return value if isinstance(value, dict) else {}


def data_rows(models: dict[str, Any]) -> list[dict[str, Any]]:
    rows = models.get("data")
    return (
        [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    )


def worker_from_url(url: Any) -> str:
    text = clean(url)
    if "192.168.2.151" in text:
        return "spark-151"
    if "192.168.2.150" in text:
        return "spark-150"
    if "192.168.2.133" in text or "127.0.0.1" in text:
        return "mac-mini-133"
    return ""


def workers_for_model(models: dict[str, Any], model_id: str) -> list[str]:
    workers: list[str] = []
    for row in data_rows(models):
        if clean(row.get("id")) != model_id and clean(row.get("model")) != model_id:
            continue
        urls = row.get("hosts") if isinstance(row.get("hosts"), list) else []
        if not urls and row.get("host"):
            urls = [row.get("host")]
        for url in urls:
            worker = worker_from_url(url)
            if worker and worker not in workers:
                workers.append(worker)
    return workers


def all_model_workers(models: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in data_rows(models):
        model = clean(row.get("id") or row.get("model"))
        if model:
            out[model] = workers_for_model(models, model)
    return out


def route_policy(warm_policy: dict[str, Any]) -> dict[str, Any]:
    value = warm_policy.get("route_policy")
    return value if isinstance(value, dict) else {}


def policy_lifecycle(snapshots: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ready = payload(snapshots, "readyz")
    policy = ready.get("policy") if isinstance(ready.get("policy"), dict) else {}
    warm = payload(snapshots, "warm_policy")
    lifecycle = (
        warm.get("policy_lifecycle")
        if isinstance(warm.get("policy_lifecycle"), dict)
        else {}
    )
    return {**lifecycle, **policy}


def scenario(
    scenario_id: str,
    status: str,
    *,
    summary: str,
    evidence: dict[str, Any] | None = None,
    failures: list[str] | None = None,
    destructive_required: bool = False,
) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "status": status,
        "passed": status == "pass",
        "destructive_required": destructive_required,
        "summary": summary,
        "evidence": evidence or {},
        "failures": failures or [],
    }


def evaluate_all_nodes_healthy(snapshots: dict[str, dict[str, Any]]) -> dict[str, Any]:
    lifecycle = policy_lifecycle(snapshots)
    models = payload(snapshots, "models")
    qwen27_workers = workers_for_model(models, "qwen3.6:27b")
    qwen35_workers = workers_for_model(models, "qwen3.6:35b-a3b-q4_K_M")
    heavy_on_133 = [
        model
        for model, workers in all_model_workers(models).items()
        if ("qwen3.6" in model or "qwen3.5:122" in model) and "mac-mini-133" in workers
    ]
    failures: list[str] = []
    if snapshots.get("readyz", {}).get("http_status") != 200:
        failures.append("readyz_not_200")
    if lifecycle.get("lifecycle_state") not in {"valid", "expiring_soon", "ok"} and (
        lifecycle.get("state") not in {"valid", "expiring_soon"}
    ):
        failures.append("policy_lifecycle_not_valid")
    if "spark-151" not in qwen27_workers:
        failures.append("qwen36_27b_not_on_spark151")
    if "spark-151" not in qwen35_workers:
        failures.append("qwen36_35b_not_on_spark151")
    if heavy_on_133:
        failures.append("heavy_models_on_2_133")
    return scenario(
        "all_nodes_healthy",
        "fail" if failures else "pass",
        summary="Front door is ready and Qwen brain placement matches policy.",
        evidence={
            "policy_lifecycle": lifecycle,
            "qwen3.6:27b_workers": qwen27_workers,
            "qwen3.6:35b-a3b-q4_K_M_workers": qwen35_workers,
            "heavy_models_on_2_133": heavy_on_133,
        },
        failures=failures,
    )


def evaluate_cloud_disabled(snapshots: dict[str, dict[str, Any]]) -> dict[str, Any]:
    policy = route_policy(payload(snapshots, "warm_policy"))
    cloud = (
        policy.get("cloud_policy")
        if isinstance(policy.get("cloud_policy"), dict)
        else {}
    )
    failures: list[str] = []
    if policy.get("allow_cloud_proxy") is not False:
        failures.append("allow_cloud_proxy_not_false")
    if policy.get("allow_cloud_tool_proxy") is not False:
        failures.append("allow_cloud_tool_proxy_not_false")
    if clean(policy.get("escalation_policy")) != "explicit_cloud_only":
        failures.append("escalation_policy_not_explicit_cloud_only")
    if cloud.get("cloud_proxy_counts_as_cloud") is not True:
        failures.append("cloud_proxy_not_counted_as_cloud")
    return scenario(
        "cloud_llm_disabled",
        "fail" if failures else "pass",
        summary="Policy blocks hidden cloud proxying and requires explicit cloud escalation.",
        evidence={
            "allow_cloud_proxy": policy.get("allow_cloud_proxy"),
            "allow_cloud_tool_proxy": policy.get("allow_cloud_tool_proxy"),
            "escalation_policy": policy.get("escalation_policy"),
            "cloud_policy": cloud,
        },
        failures=failures,
    )


def evaluate_capability_gate(snapshots: dict[str, dict[str, Any]]) -> dict[str, Any]:
    policy = route_policy(payload(snapshots, "warm_policy"))
    capability_gates = (
        policy.get("capability_gates")
        if isinstance(policy.get("capability_gates"), dict)
        else {}
    )
    benchmark_gates = (
        policy.get("benchmark_gates")
        if isinstance(policy.get("benchmark_gates"), dict)
        else {}
    )
    exemptions = (
        benchmark_gates.get("capability_gate_exemptions")
        if isinstance(benchmark_gates.get("capability_gate_exemptions"), dict)
        else {}
    )
    failures: list[str] = []
    if capability_gates.get("unproven_allows_manual_or_lab_only") is not True:
        failures.append("unproven_capability_not_limited_to_manual_or_lab")
    if benchmark_gates.get("production_route_requires_capability_gate") is not True:
        failures.append("global_capability_gate_not_required")
    if "low_risk_local_text_non_mutating" not in exemptions:
        failures.append("low_risk_exemption_not_named")
    return scenario(
        "capability_packet_unproven",
        "fail" if failures else "pass",
        summary=(
            "Unproven capability evidence remains limited to manual/lab, with an "
            "explicit low-risk local text exemption."
        ),
        evidence={
            "capability_gates": capability_gates,
            "benchmark_gate_policy": benchmark_gates,
        },
        failures=failures,
    )


def evaluate_specialist_degraded(
    snapshots: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    overview = payload(snapshots, "overview")
    health = overview.get("health") if isinstance(overview.get("health"), dict) else {}
    downstreams = (
        health.get("downstreams") if isinstance(health.get("downstreams"), dict) else {}
    )
    models = payload(snapshots, "models")
    specialist_models = {
        "ocr": workers_for_model(models, "paddleocr:PP-OCRv6-small"),
        "rerank": workers_for_model(models, "BAAI/bge-reranker-v2-m3"),
        "embed": workers_for_model(models, "bge-m3:latest"),
    }
    local_errors: dict[str, list[dict[str, Any]]] = {}
    for lane in ("ocr", "rerank", "safety"):
        rows = downstreams.get(lane)
        if not isinstance(rows, list):
            continue
        errored = [
            row
            for row in rows
            if isinstance(row, dict)
            and clean(row.get("status")).lower() in {"error", "offline"}
        ]
        if errored:
            local_errors[lane] = errored
    failures: list[str] = []
    if not any(specialist_models.values()):
        failures.append("no_peer_specialist_models_visible")
    if not local_errors:
        return scenario(
            "specialist_service_unavailable",
            "not_exercised",
            summary=(
                "No unavailable specialist replica was visible during this capture; "
                "run an outage drill to prove fallback."
            ),
            evidence={"specialist_workers": specialist_models},
            destructive_required=True,
        )
    return scenario(
        "specialist_service_unavailable",
        "fail" if failures else "pass",
        summary="At least one local specialist replica is unavailable and peer specialist lanes remain visible.",
        evidence={
            "local_specialist_errors": local_errors,
            "specialist_workers": specialist_models,
        },
        failures=failures,
    )


def external_evidence_result(
    scenario_id: str,
    external: dict[str, Any],
) -> dict[str, Any] | None:
    scenarios = external.get("scenarios")
    if not isinstance(scenarios, dict):
        return None
    item = scenarios.get(scenario_id)
    if not isinstance(item, dict):
        return None
    status = clean(item.get("status")) or "not_exercised"
    return scenario(
        scenario_id,
        status,
        summary=clean(item.get("summary")) or "External outage-drill evidence.",
        evidence=item.get("evidence") if isinstance(item.get("evidence"), dict) else {},
        failures=item.get("failures") if isinstance(item.get("failures"), list) else [],
        destructive_required=bool(item.get("destructive_required", True)),
    )


def destructive_placeholder(scenario_id: str) -> dict[str, Any]:
    return scenario(
        scenario_id,
        "not_exercised",
        summary="Requires an operator-approved outage drill or injected worker-isolation evidence.",
        evidence={"required_external_evidence": True},
        destructive_required=True,
    )


def evaluate_matrix(
    snapshots: dict[str, dict[str, Any]],
    *,
    external_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    external = external_evidence or {}
    scenarios = [
        evaluate_all_nodes_healthy(snapshots),
        external_evidence_result("spark_151_unavailable", external)
        or destructive_placeholder("spark_151_unavailable"),
        external_evidence_result("spark_150_unavailable", external)
        or destructive_placeholder("spark_150_unavailable"),
        external_evidence_result("both_sparks_unavailable_2_133_available", external)
        or destructive_placeholder("both_sparks_unavailable_2_133_available"),
        external_evidence_result("all_local_inference_unavailable", external)
        or destructive_placeholder("all_local_inference_unavailable"),
        evaluate_cloud_disabled(snapshots),
        external_evidence_result("explicit_cloud_escalation", external)
        or destructive_placeholder("explicit_cloud_escalation"),
        external_evidence_result("stale_benchmark_packet", external)
        or destructive_placeholder("stale_benchmark_packet"),
        evaluate_capability_gate(snapshots),
        evaluate_specialist_degraded(snapshots),
        external_evidence_result("policy_refresh_failure", external)
        or destructive_placeholder("policy_refresh_failure"),
        external_evidence_result("worker_substitution", external)
        or destructive_placeholder("worker_substitution"),
    ]
    passed = [item for item in scenarios if item["status"] == "pass"]
    failed = [item for item in scenarios if item["status"] == "fail"]
    not_exercised = [item for item in scenarios if item["status"] == "not_exercised"]
    return {
        "schema": SCHEMA,
        "generated_at": utc_now(),
        "scenario_count": len(scenarios),
        "pass_count": len(passed),
        "fail_count": len(failed),
        "not_exercised_count": len(not_exercised),
        "passed": not failed and not not_exercised,
        "release_gate": {
            "passed": not failed and not not_exercised,
            "reason": "all_degraded_scenarios_exercised"
            if not failed and not not_exercised
            else "degraded_matrix_incomplete_or_failed",
            "not_exercised": [item["scenario_id"] for item in not_exercised],
            "failed": [item["scenario_id"] for item in failed],
        },
        "scenarios": scenarios,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontdoor", default=DEFAULT_FRONTDOOR)
    parser.add_argument("--fixture-dir", type=Path)
    parser.add_argument("--external-evidence", type=Path)
    parser.add_argument(
        "--output-json", type=Path, default=Path("tmp/degraded-estate-matrix.json")
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    snapshots = (
        fixture_snapshots(args.fixture_dir)
        if args.fixture_dir
        else live_snapshots(args.frontdoor)
    )
    external = load_json(args.external_evidence) if args.external_evidence else {}
    packet = evaluate_matrix(snapshots, external_evidence=external)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n")
    print(json.dumps(packet["release_gate"], sort_keys=True))
    return 0 if packet["fail_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
