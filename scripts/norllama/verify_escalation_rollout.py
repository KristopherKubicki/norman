#!/usr/bin/env python3
"""Verify the signed resident-first escalation rollout end to end."""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RECEIPT_SCHEMA = "norman.norllama.escalation-acceptance.v1"
DEFAULT_BASE_URL = "https://llm.home.arpa"
INFERENCE_MARKER = "NORMAN_RESIDENT_ACCEPTANCE_OK"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_request(
    base_url: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = 30.0,
    insecure: bool = False,
) -> tuple[dict[str, Any], float]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        data=body,
        headers=headers,
        method="POST" if body is not None else "GET",
    )
    context = (
        ssl._create_unverified_context()  # noqa: SLF001 - internal estate TLS
        if insecure
        else None
    )
    started = time.monotonic()
    with urllib.request.urlopen(
        request,
        timeout=timeout_seconds,
        context=context,
    ) as response:
        decoded = json.loads(response.read().decode("utf-8"))
    elapsed_ms = round((time.monotonic() - started) * 1000, 1)
    if not isinstance(decoded, dict):
        raise RuntimeError(f"{path} returned a non-object JSON payload")
    return decoded, elapsed_ms


def _model_ids(payload: dict[str, Any]) -> set[str]:
    rows = payload.get("data")
    if not isinstance(rows, list):
        rows = payload.get("models")
    if not isinstance(rows, list):
        return set()
    model_ids: set[str] = set()
    for row in rows:
        if isinstance(row, str):
            model_id = row
        elif isinstance(row, dict):
            model_id = row.get("id") or row.get("model") or row.get("name")
        else:
            continue
        if str(model_id or "").strip():
            model_ids.add(str(model_id).strip())
    return model_ids


def _visible_answer(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first, dict) else {}
    if not isinstance(message, dict):
        return ""
    return str(message.get("content") or "").strip()


def run_acceptance(
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = 30.0,
    insecure: bool = False,
    run_inference: bool = True,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def record(name: str, ok: bool, elapsed_ms: float, detail: str = "") -> None:
        checks.append(
            {
                "name": name,
                "status": "passed" if ok else "failed",
                "elapsed_ms": elapsed_ms,
                "detail": detail,
            }
        )
        if not ok:
            raise RuntimeError(f"{name}: {detail or 'acceptance check failed'}")

    health, elapsed = _json_request(
        base_url,
        "/healthz",
        timeout_seconds=timeout_seconds,
        insecure=insecure,
    )
    record("health", bool(health.get("ok", True)), elapsed)

    readiness, elapsed = _json_request(
        base_url,
        "/readyz",
        timeout_seconds=timeout_seconds,
        insecure=insecure,
    )
    ready = bool(readiness.get("ready"))
    policy = readiness.get("policy") if isinstance(readiness.get("policy"), dict) else {}
    record(
        "signed_policy_ready",
        ready and bool(policy.get("policy_id")),
        elapsed,
        str(policy.get("lifecycle_state") or policy.get("reason") or ""),
    )

    scenarios = (
        (
            "resident_default",
            {"lane": "helpdesk", "risk": "low", "complexity": "simple"},
            "resident",
            False,
        ),
        (
            "economy_escalation",
            {"lane": "llm_prep", "complexity": "moderate"},
            "economy",
            False,
        ),
        (
            "authority_boundary",
            {"lane": "data_operations", "side_effects": True},
            "authority",
            True,
        ),
        (
            "frontier_fail_closed",
            {"requested_role": "frontier", "final_check": True},
            "authority",
            False,
        ),
        (
            "frontier_after_authority",
            {
                "requested_role": "frontier",
                "final_check": True,
                "prior_roles": ["authority"],
            },
            "frontier",
            False,
        ),
    )
    decisions: dict[str, dict[str, Any]] = {}
    for name, request_payload, expected_role, expected_approval in scenarios:
        decision, elapsed = _json_request(
            base_url,
            "/v1/escalation/shadow",
            payload=request_payload,
            timeout_seconds=timeout_seconds,
            insecure=insecure,
        )
        decisions[name] = decision
        role_matches = decision.get("proposed_role") == expected_role
        approval_matches = (
            bool(decision.get("approval_required")) is expected_approval
        )
        shadow_only = (
            decision.get("mode") == "shadow_only"
            and decision.get("execution_authority_changed") is False
        )
        record(
            name,
            role_matches and approval_matches and shadow_only,
            elapsed,
            (
                f"expected={expected_role}, "
                f"observed={decision.get('proposed_role')}"
            ),
        )

    blocked_gate = decisions["frontier_fail_closed"].get("frontier_gate")
    allowed_gate = decisions["frontier_after_authority"].get("frontier_gate")
    record(
        "frontier_gate",
        isinstance(blocked_gate, dict)
        and blocked_gate.get("passed") is False
        and isinstance(allowed_gate, dict)
        and allowed_gate.get("passed") is True,
        0.0,
    )

    resident_decision = decisions["resident_default"]
    resident_model = str(resident_decision.get("proposed_model") or "").strip()
    registry_version = str(resident_decision.get("registry_version") or "").strip()
    models, elapsed = _json_request(
        base_url,
        "/v1/models",
        timeout_seconds=max(timeout_seconds, 10.0),
        insecure=insecure,
    )
    advertised_models = _model_ids(models)
    record(
        "resident_model_advertised",
        bool(resident_model) and resident_model in advertised_models,
        elapsed,
        resident_model,
    )

    if run_inference:
        completion, elapsed = _json_request(
            base_url,
            "/v1/chat/completions",
            payload={
                "model": resident_model,
                "messages": [
                    {
                        "role": "user",
                        "content": f"Reply with exactly: {INFERENCE_MARKER}",
                    }
                ],
                "temperature": 0,
                "max_tokens": 96,
                "stream": False,
            },
            timeout_seconds=max(timeout_seconds, 120.0),
            insecure=insecure,
        )
        answer = _visible_answer(completion)
        record(
            "resident_visible_inference",
            answer == INFERENCE_MARKER,
            elapsed,
            f"model={resident_model}, visible_content={bool(answer)}",
        )

    roles = {}
    for decision in decisions.values():
        role = str(decision.get("proposed_role") or "")
        model = str(decision.get("proposed_model") or "")
        if role and model:
            roles[role] = model
    return {
        "schema": RECEIPT_SCHEMA,
        "status": "passed",
        "checked_at": _iso_now(),
        "base_url": base_url,
        "policy_id": str(policy.get("policy_id") or ""),
        "registry_version": registry_version,
        "roles": roles,
        "checks": checks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--skip-inference", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        receipt = run_acceptance(
            base_url=args.base_url,
            timeout_seconds=max(1.0, args.timeout_seconds),
            insecure=args.insecure,
            run_inference=not args.skip_inference,
        )
    except (RuntimeError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "status": "failed",
            "checked_at": _iso_now(),
            "base_url": args.base_url,
            "error": str(exc),
        }
    rendered = json.dumps(receipt, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
