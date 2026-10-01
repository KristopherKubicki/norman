#!/usr/bin/env python3
"""Stable manifests and per-case receipts for resumable benchmark execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "norman.norllama.benchmark-suite-manifest.v1"
CASE_RECEIPT_SCHEMA = "norman.norllama.benchmark-case-receipt.v1"
ANSWER_SCHEMA = "norman.planner-llm-benchmark-answers.v2"
CASE_HASH_FIELDS = (
    "case_id",
    "title",
    "family",
    "prompt",
    "required_terms",
    "forbidden_terms",
    "precision_checks",
    "promotion_weight",
)
PROMPT_HASH_FIELDS = (
    "prompt_id",
    "case_id",
    "candidate_id",
    "model",
    "provider_surface",
    "service_tier",
    "input_tokens",
    "cached_input_tokens",
    "expected_output_tokens",
    "answer_contract",
)


def utc_now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _selected_fields(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: row.get(field) for field in fields if field in row}


def case_hash(case: dict[str, Any], prompt: dict[str, Any]) -> str:
    """Hash all case and prompt semantics that can affect a scored response."""

    return sha256_json(
        {
            "case": _selected_fields(case, CASE_HASH_FIELDS),
            "prompt": _selected_fields(prompt, PROMPT_HASH_FIELDS),
        }
    )


def _suite_content(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "packet_schema": _clean(packet.get("schema")),
        "cases": [
            _selected_fields(case, CASE_HASH_FIELDS)
            for case in packet.get("cases") or []
            if isinstance(case, dict)
        ],
        "prompts": [
            _selected_fields(prompt, PROMPT_HASH_FIELDS)
            for prompt in packet.get("prompts") or []
            if isinstance(prompt, dict)
        ],
        "promotion_policy": packet.get("promotion_policy") or {},
        "precision_policy": packet.get("precision_policy") or {},
    }


def build_suite_manifest(
    *,
    packet: dict[str, Any],
    suite_id: str,
    profile: dict[str, Any],
    scorer_version: str,
) -> dict[str, Any]:
    """Build a canonical manifest that excludes run timestamps and mutable output."""

    case_by_id = {
        _clean(case.get("case_id")): case
        for case in packet.get("cases") or []
        if isinstance(case, dict) and _clean(case.get("case_id"))
    }
    cases = []
    for prompt in packet.get("prompts") or []:
        if not isinstance(prompt, dict):
            continue
        case = case_by_id.get(_clean(prompt.get("case_id"))) or {}
        cases.append(
            {
                "case_id": _clean(prompt.get("case_id")),
                "prompt_id": _clean(prompt.get("prompt_id")),
                "case_hash": case_hash(case, prompt),
            }
        )
    content = _suite_content(packet)
    unsigned = {
        "schema": MANIFEST_SCHEMA,
        "suite_id": _clean(suite_id) or "unspecified",
        "suite_content_hash": sha256_json(content),
        "packet_schema": _clean(packet.get("schema")),
        "scorer_version": _clean(scorer_version),
        "profile": {
            key: _clean(profile.get(key))
            for key in (
                "name",
                "route_id",
                "model",
                "transport",
                "provider_surface",
                "service_tier",
                "base_url",
            )
        },
        "cases": cases,
    }
    manifest = dict(unsigned)
    manifest["manifest_hash"] = sha256_json(unsigned)
    return manifest


def manifest_case_hash(manifest: dict[str, Any], prompt_id: str) -> str:
    for row in manifest.get("cases") or []:
        if isinstance(row, dict) and _clean(row.get("prompt_id")) == _clean(prompt_id):
            return _clean(row.get("case_hash"))
    return ""


def answer_state(
    row: dict[str, Any],
    *,
    max_case_attempts: int = 3,
) -> str:
    """Classify a persisted answer row without letting a transport error look done."""

    if _clean(row.get("answer")):
        return "complete"
    attempts = max(0, int(row.get("attempt_count") or 0))
    error = _clean(row.get("error"))
    if error and attempts >= max(1, max_case_attempts):
        return "failed"
    if error or attempts:
        return "retryable"
    return "pending"


def should_execute_case(
    row: dict[str, Any],
    *,
    max_case_attempts: int = 3,
) -> bool:
    return answer_state(row, max_case_attempts=max_case_attempts) in {
        "pending",
        "retryable",
    }


def prepare_answer_row(
    row: dict[str, Any],
    *,
    manifest: dict[str, Any],
    max_case_attempts: int = 3,
) -> dict[str, Any]:
    """Attach a manifest-bound execution contract to one mutable answer row."""

    prepared = dict(row)
    expected_hash = manifest_case_hash(manifest, _clean(row.get("prompt_id")))
    matching_contract = (
        bool(expected_hash)
        and _clean(row.get("case_hash")) == expected_hash
        and _clean(row.get("suite_manifest_hash"))
        == _clean(manifest.get("manifest_hash"))
    )
    legacy_row = not _clean(row.get("case_hash")) and not _clean(
        row.get("suite_manifest_hash")
    )
    if not matching_contract and not legacy_row:
        prepared.update(
            {
                "answer": "",
                "error": "",
                "attempt_count": 0,
                "attempts": [],
                "receipt_artifact": "",
            }
        )
    prepared["case_hash"] = expected_hash
    prepared["suite_manifest_hash"] = _clean(manifest.get("manifest_hash"))
    if legacy_row:
        prepared["contract_migrated_from_legacy"] = True
    prepared["execution_state"] = answer_state(
        prepared, max_case_attempts=max_case_attempts
    )
    return prepared


def _receipt_component(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-") or "case"


def write_case_receipt(
    *,
    receipts_root: Path,
    manifest: dict[str, Any],
    row: dict[str, Any],
    event: str,
    details: dict[str, Any] | None = None,
) -> Path:
    """Append one immutable case receipt. Existing receipts are never replaced."""

    case_id = _receipt_component(_clean(row.get("case_id")))
    case_digest = _clean(row.get("case_hash"))[:16] or "nohash"
    target = receipts_root / f"{case_id}-{case_digest}"
    target.mkdir(parents=True, exist_ok=True)
    attempt = max(1, int(row.get("attempt_count") or 0))
    payload = {
        "schema": CASE_RECEIPT_SCHEMA,
        "recorded_at": utc_now(),
        "event": _clean(event),
        "suite_manifest_hash": _clean(manifest.get("manifest_hash")),
        "suite_id": _clean(manifest.get("suite_id")),
        "case_id": _clean(row.get("case_id")),
        "prompt_id": _clean(row.get("prompt_id")),
        "case_hash": _clean(row.get("case_hash")),
        "attempt_count": attempt,
        "execution_state": _clean(row.get("execution_state")),
        "answer_present": bool(_clean(row.get("answer"))),
        "error": _clean(row.get("error")),
        "usage": {
            "input_tokens": int(row.get("input_tokens") or 0),
            "cached_input_tokens": int(row.get("cached_input_tokens") or 0),
            "output_tokens": int(row.get("output_tokens") or 0),
            "latency_ms": int(row.get("latency_ms") or 0),
        },
        "details": dict(details or {}),
    }
    name = f"attempt-{attempt:03d}.json"
    path = target / name
    if path.exists():
        path = target / f"attempt-{attempt:03d}-{time.time_ns()}.json"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    with os.fdopen(os.open(path, flags, 0o644), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def execution_summary(
    rows: list[dict[str, Any]],
    *,
    max_case_attempts: int = 3,
) -> dict[str, int]:
    states = [
        answer_state(row, max_case_attempts=max_case_attempts)
        for row in rows
        if isinstance(row, dict)
    ]
    return {
        "total": len(states),
        "complete": states.count("complete"),
        "pending": states.count("pending"),
        "retryable": states.count("retryable"),
        "failed": states.count("failed"),
    }
