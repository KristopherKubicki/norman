#!/usr/bin/env python3
"""Execute Norllama capability cases from a route-proof manifest.

The benchmark-packet generator defines the cases Norman must eventually prove.
This runner turns a selected subset of that manifest into an execution-results
artifact. Dry-run rows and fixture-missing rows are intentionally never
promotion-authoritative.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from route_proof_benchmark_packet import (  # noqa: E402
    DEFAULT_FRONTDOOR,
    OCR_SMOKE_PNG_BASE64,
    clean,
    count_int,
    normalize_worker_name,
    sha256_text,
    worker_from_url,
    write_json_document,
)
from app.services.norllama.route_proof import (  # noqa: E402
    audit_route_receipt,
    normalize_route_receipt_for_completion_gate,
    receipt_completion_gate_passes,
)


RESULT_SCHEMA = "norman.norllama.capability-execution-results.v1"
CAPABILITY_SCORER_VERSION = "norman.capability-scorer.v2"
DEFAULT_MANIFEST = Path("tmp/capability-execution-manifest-latest.json")
DEFAULT_OUTPUT = Path("tmp/capability-execution-results-latest.json")
DEFAULT_ASR_FIXTURE = Path("tmp/norllama-asr-route-proof.wav")
DEFAULT_ASR_FIXTURE_TEXT = "norman local canary"
DEFAULT_OCR_FIXTURE_DIR = Path("tmp/capability-ocr-fixtures")
DEFAULT_OCR_FONT = Path("/usr/share/fonts/opentype/cantarell/Cantarell-Regular.otf")
OCR_FIXTURE_SPECS: tuple[dict[str, str], ...] = (
    {
        "fixture_id": "ocr-clean-route-proof",
        "filename": "ocr-clean-route-proof.png",
        "text": "ROUTE PROOF OK\nNORMAN OCR CANARY",
        "variant": "clean",
    },
    {
        "fixture_id": "ocr-ledger-id",
        "filename": "ocr-ledger-id.png",
        "text": "LEDGER 42\nWORKER SPARK 150",
        "variant": "ledger",
    },
    {
        "fixture_id": "ocr-warning-banner",
        "filename": "ocr-warning-banner.png",
        "text": "LOCAL ONLY\nNO CLOUD FALLBACK",
        "variant": "policy",
    },
)
CORE_AGENT_SUITES = {"planner_router", "coder", "verifier_judge"}
SUPPORTED_SUITES = {"ocr", "reranker", "safety"} | CORE_AGENT_SUITES
ASR_SUITE = "asr"
CORE_AGENT_MODELS = {
    "planner_router": "qwen3.6:35b-a3b-q4_K_M",
    "coder": "qwen3.6:27b",
    "verifier_judge": "qwen3.6:27b",
}
CORE_AGENT_OPERATION = {
    "planner_router": "route_decision",
    "coder": "code_reasoning",
    "verifier_judge": "judge_verdict",
}
CASE_HASH_FIELDS = (
    "case_id",
    "case_revision",
    "title",
    "prompt",
    "expected_route_mode",
    "expected_lane",
    "expected_provider",
    "expected_phases",
    "expected_specialist_lanes",
    "expected_deterministic_experts",
    "expected_worker_policy",
    "expected_output_shape",
    "cloud_policy",
    "risk_level",
    "expected_label",
    "expected_policy_action",
    "required_operations",
    "document_structure",
    "injection_policy",
    "benchmark_assertions",
    "tags",
)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    payload: dict[str, Any]
    headers: dict[str, str]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tls_context(verify_tls: bool) -> ssl.SSLContext | None:
    return None if verify_tls else ssl._create_unverified_context()


def http_json_request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: float = 60.0,
    verify_tls: bool = False,
) -> HttpResponse:
    request_headers = {
        "User-Agent": "norman-capability-execution-runner/1.0",
        **(headers or {}),
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers=request_headers,
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds,
            context=_tls_context(verify_tls),
        ) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw.strip() else {}
            payload_dict = parsed if isinstance(parsed, dict) else {}
            response_headers = {
                str(key).lower(): str(value) for key, value in response.headers.items()
            }
            return HttpResponse(
                status=int(response.status),
                payload=payload_dict,
                headers=response_headers,
            )
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            parsed = {"error": raw.strip()}
        return HttpResponse(
            status=int(exc.code),
            payload=parsed if isinstance(parsed, dict) else {"error": raw.strip()},
            headers={str(k).lower(): str(v) for k, v in exc.headers.items()},
        )


def load_manifest(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text())
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return parsed


def case_hash_payload(case: dict[str, Any]) -> dict[str, Any]:
    return {field: case.get(field) for field in CASE_HASH_FIELDS if field in case}


def recompute_case_hash(case: dict[str, Any]) -> str:
    return sha256_text(case_hash_payload(case))


def input_spec_for_case(case: dict[str, Any]) -> dict[str, Any]:
    input_spec = case.get("input_spec")
    if isinstance(input_spec, dict):
        return input_spec
    return {
        "input_type": "text",
        "prompt": clean(case.get("prompt")),
    }


def recompute_input_hash(case: dict[str, Any]) -> str:
    return sha256_text(input_spec_for_case(case))


def execution_instance_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "norman.capability-execution-instance.v1",
        "suite_id": clean(result.get("suite_id")),
        "case_id": clean(result.get("case_id")),
        "case_hash": clean(result.get("case_hash")),
        "input_hash": clean(result.get("input_hash")),
        "fixture_id": clean(result.get("fixture_id")),
        "fixture_sha256": clean(result.get("fixture_sha256")),
        "input_artifact_hashes": [
            clean(item)
            for item in result.get("input_artifact_hashes", [])
            if clean(item)
        ],
        "requested_model": clean(result.get("requested_model")),
        "endpoint": clean(result.get("endpoint")),
        "expected_worker_policy": clean(result.get("expected_worker_policy")),
        "target_worker": clean(result.get("target_worker")),
        "scorer_version": clean(result.get("scorer_version"))
        or CAPABILITY_SCORER_VERSION,
    }


def execution_instance_hash(result: dict[str, Any]) -> str:
    return sha256_text(execution_instance_payload(result))


def verify_case_contract(case: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if not clean(case.get("prompt")):
        failures.append("missing_prompt")
    if clean(case.get("input_hash")) != recompute_input_hash(case):
        failures.append("input_hash_mismatch")
    expected_case_hash = clean(case.get("case_hash"))
    if not expected_case_hash:
        failures.append("missing_case_hash")
    elif expected_case_hash != recompute_case_hash(case):
        failures.append("case_hash_mismatch")
    return failures


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_asr_fixture(*, output: Path, text: str) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    safe_text = " ".join(text.replace("'", " ").split()).strip()
    if not safe_text:
        safe_text = DEFAULT_ASR_FIXTURE_TEXT
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"flite=text='{safe_text}'",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(output),
    ]
    subprocess.run(command, check=True)
    return {
        "fixture_id": "asr-route-proof-flite",
        "suite_id": ASR_SUITE,
        "path": str(output),
        "sha256": file_sha256(output) if output.exists() else "",
        "generator": "ffmpeg_flite",
        "text": safe_text,
        "media_type": "audio/wav",
        "generated": True,
        "size_bytes": output.stat().st_size if output.exists() else 0,
    }


def generate_ocr_fixtures(
    *,
    output_dir: Path,
    font_path: Path = DEFAULT_OCR_FONT,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    fixtures: list[dict[str, Any]] = []
    for spec in OCR_FIXTURE_SPECS:
        output = output_dir / spec["filename"]
        command = [
            "convert",
            "-size",
            "900x240",
            "xc:white",
            "-font",
            str(font_path),
            "-fill",
            "black",
            "-pointsize",
            "46",
            "-gravity",
            "center",
            "-annotate",
            "0",
            spec["text"],
            str(output),
        ]
        subprocess.run(command, check=True)
        fixtures.append(
            {
                "fixture_id": spec["fixture_id"],
                "suite_id": "ocr",
                "path": str(output),
                "sha256": file_sha256(output) if output.exists() else "",
                "generator": "imagemagick_convert",
                "text": spec["text"],
                "media_type": "image/png",
                "variant": spec["variant"],
                "generated": True,
                "size_bytes": output.stat().st_size if output.exists() else 0,
            }
        )
    return fixtures


def manifest_cases(
    manifest: dict[str, Any],
    *,
    suites: set[str] | None = None,
) -> list[dict[str, Any]]:
    suite_map = manifest.get("suites")
    if not isinstance(suite_map, dict):
        return []
    rows: list[dict[str, Any]] = []
    for suite_id in sorted(suite_map):
        if suites and suite_id not in suites:
            continue
        suite = suite_map.get(suite_id)
        cases = suite.get("cases") if isinstance(suite, dict) else None
        if not isinstance(cases, list):
            continue
        suite_version = clean(suite.get("suite_version"))
        suite_hash = clean(suite.get("suite_hash"))
        for case in cases:
            if isinstance(case, dict):
                row = dict(case)
                row["suite_id"] = suite_id
                row["suite_version"] = suite_version
                row["suite_hash"] = suite_hash
                rows.append(row)
    return rows


def select_cases(
    manifest: dict[str, Any],
    *,
    suites: set[str] | None = None,
    limit_per_suite: int = 1,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    by_suite: dict[str, list[dict[str, Any]]] = {}
    for case in manifest_cases(manifest, suites=suites):
        by_suite.setdefault(clean(case.get("suite_id")), []).append(case)
    for suite_id in sorted(by_suite):
        cases = by_suite[suite_id]
        if limit_per_suite <= 0:
            selected.extend(cases)
            continue
        selected.extend(stratified_suite_cases(cases, limit=limit_per_suite))
    return selected


def stratified_suite_cases(
    cases: list[dict[str, Any]], *, limit: int
) -> list[dict[str, Any]]:
    if limit <= 0 or len(cases) <= limit:
        return list(cases)
    suite_id = clean(cases[0].get("suite_id")) if cases else ""
    if suite_id == "safety":
        return stratify_by_key(cases, limit=limit, key="expected_label")
    if suite_id == "reranker":
        return stratify_by_tags(cases, limit=limit)
    if suite_id in {"ocr", ASR_SUITE}:
        return stratify_by_key(cases, limit=limit, key="expected_label")
    return list(cases[:limit])


def stratify_by_key(
    cases: list[dict[str, Any]],
    *,
    limit: int,
    key: str,
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        bucket = clean(case.get(key)) or "unknown"
        buckets.setdefault(bucket, []).append(case)
    return round_robin_buckets(buckets, limit=limit)


def stratify_by_tags(
    cases: list[dict[str, Any]], *, limit: int
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        tags = case.get("tags") if isinstance(case.get("tags"), list) else []
        bucket = clean(tags[0] if tags else "") or "untagged"
        buckets.setdefault(bucket, []).append(case)
    return round_robin_buckets(buckets, limit=limit)


def round_robin_buckets(
    buckets: dict[str, list[dict[str, Any]]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    bucket_names = list(buckets)
    index = 0
    while len(selected) < limit and bucket_names:
        bucket = bucket_names[index % len(bucket_names)]
        rows = buckets[bucket]
        if rows:
            selected.append(rows.pop(0))
        bucket_names = [name for name in bucket_names if buckets[name]]
        index += 1
    return selected


def attach_suite_fixtures(
    cases: list[dict[str, Any]],
    *,
    suite_id: str,
    fixtures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not fixtures:
        return cases
    fixture_index = 0
    updated: list[dict[str, Any]] = []
    for case in cases:
        if clean(case.get("suite_id")) != suite_id:
            updated.append(case)
            continue
        fixture = fixtures[fixture_index % len(fixtures)]
        fixture_index += 1
        case_copy = dict(case)
        case_copy["fixture_path"] = clean(fixture.get("path"))
        case_copy["fixture_text"] = clean(fixture.get("text"))
        case_copy["fixture_id"] = clean(fixture.get("fixture_id"))
        case_copy["fixture_sha256"] = clean(fixture.get("sha256"))
        case_copy["fixture_media_type"] = clean(fixture.get("media_type"))
        updated.append(case_copy)
    return updated


def response_route(payload: dict[str, Any]) -> dict[str, Any]:
    route = payload.get("norllama")
    return route if isinstance(route, dict) else {}


def response_usage(payload: dict[str, Any]) -> dict[str, int]:
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    input_tokens = count_int(usage.get("prompt_tokens") or usage.get("input_tokens"))
    output_tokens = count_int(
        usage.get("completion_tokens") or usage.get("output_tokens")
    )
    total_tokens = count_int(usage.get("total_tokens"))
    if not total_tokens:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def local_work_units(case: dict[str, Any], payload: dict[str, Any]) -> tuple[int, str]:
    suite_id = clean(case.get("suite_id"))
    if suite_id in CORE_AGENT_SUITES:
        return 1, "model_completion"
    if suite_id == "safety":
        return 1, "safety_classification"
    if suite_id == "reranker":
        results = payload.get("results")
        result_count = len(results) if isinstance(results, list) else 1
        return max(1, result_count), "documents_ranked"
    if suite_id == "ocr":
        line_count = count_int(payload.get("line_count"))
        if not line_count:
            text = clean(payload.get("text") or payload.get("merged_text"))
            line_count = len([line for line in text.splitlines() if line.strip()])
        return max(1, line_count), "ocr_lines"
    if suite_id == ASR_SUITE:
        return 1, "audio_clip"
    return 1, "work_unit"


def response_text_preview(payload: dict[str, Any]) -> str:
    message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    choice_content = ""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0] if isinstance(choices[0], dict) else {}
        first_message = (
            first_choice.get("message")
            if isinstance(first_choice.get("message"), dict)
            else {}
        )
        first_delta = (
            first_choice.get("delta")
            if isinstance(first_choice.get("delta"), dict)
            else {}
        )
        choice_content = clean(
            first_message.get("content")
            or first_choice.get("text")
            or first_delta.get("content")
        )
    direct = clean(
        choice_content
        or message.get("content")
        or payload.get("response")
        or payload.get("content")
        or payload.get("text")
        or payload.get("transcript")
        or payload.get("merged_text")
        or payload.get("summary")
    )
    if direct:
        return direct
    results = payload.get("results")
    if isinstance(results, list) and results:
        return json.dumps(results[:2], sort_keys=True)[:240]
    return ""


def normalized_word_set(value: str) -> set[str]:
    cleaned = "".join(
        character.lower() if character.isalnum() else " " for character in value
    )
    return {word for word in cleaned.split() if word}


def word_overlap_ratio(*, expected: str, observed: str) -> float:
    expected_words = normalized_word_set(expected)
    if not expected_words:
        return 0.0
    observed_words = normalized_word_set(observed)
    return round(len(expected_words & observed_words) / len(expected_words), 4)


def observed_worker(
    payload: dict[str, Any], headers: dict[str, str]
) -> tuple[str, str]:
    route = response_route(payload)
    upstream = clean(route.get("upstream")) or clean(headers.get("x-norllama-upstream"))
    worker = (
        normalize_worker_name(route.get("observed_worker"))
        or normalize_worker_name(route.get("selected_worker"))
        or normalize_worker_name(headers.get("x-norllama-worker-id"))
        or worker_from_url(upstream)
    )
    if not worker and isinstance(route.get("attempts"), list):
        worker = worker_from_url((route.get("attempts") or [""])[-1])
    return worker, upstream


def target_worker_for_policy(expected_worker_policy: str) -> str:
    clean_policy = clean(expected_worker_policy).lower()
    if "spark-150" in clean_policy:
        return "spark-150"
    if "spark-151" in clean_policy:
        return "spark-151"
    if "mac-mini" in clean_policy or "2.133" in clean_policy:
        return "mac-mini-133"
    return ""


def peer_path_from_response(
    *,
    route: dict[str, Any],
    headers: dict[str, str],
    frontdoor: str,
    worker: str,
) -> list[str]:
    if isinstance(route.get("peer_path"), list):
        return [clean(item) for item in route["peer_path"] if clean(item)]
    header_path = clean(headers.get("x-norllama-peer-path"))
    if header_path:
        return [clean(item) for item in header_path.split(",") if clean(item)]
    if worker:
        return [frontdoor.rstrip("/"), worker]
    return []


def case_result_metadata(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "suite_version": clean(case.get("suite_version")),
        "suite_hash": clean(case.get("suite_hash")),
        "case_revision": clean(case.get("case_revision")),
        "case_hash": clean(case.get("case_hash")),
        "case_hash_verified": clean(case.get("case_hash")) == recompute_case_hash(case),
        "input_hash": clean(case.get("input_hash")),
        "input_hash_verified": clean(case.get("input_hash"))
        == recompute_input_hash(case),
        "input_spec": input_spec_for_case(case),
        "required_operations": list(case.get("required_operations", [])),
        "document_structure": clean(case.get("document_structure")),
        "injection_policy": clean(case.get("injection_policy")),
    }


def suite_endpoint_and_payload(
    case: dict[str, Any],
    *,
    frontdoor: str,
    audio_fixture: Path | None,
) -> tuple[str, dict[str, Any], bytes | None, dict[str, str], str]:
    suite_id = clean(case.get("suite_id"))
    input_spec = input_spec_for_case(case)
    prompt = clean(
        input_spec.get("user_instruction")
        or input_spec.get("prompt")
        or case.get("prompt")
        or case.get("title")
    )
    if suite_id == "safety":
        text = safety_text_from_input_spec(input_spec, fallback_prompt=prompt)
        return (
            f"{frontdoor.rstrip('/')}/v1/safety/classify",
            {
                "text": text,
                "input_spec": input_spec,
                "model": "Qwen/Qwen3Guard-Stream-0.6B",
            },
            None,
            {"Content-Type": "application/json"},
            "Qwen/Qwen3Guard-Stream-0.6B",
        )
    if suite_id in CORE_AGENT_SUITES:
        model = CORE_AGENT_MODELS[suite_id]
        expected_lane = clean(case.get("expected_lane")) or suite_id
        instruction = {
            "case_id": clean(case.get("case_id")),
            "suite_id": suite_id,
            "title": clean(case.get("title")),
            "prompt": prompt,
            "expected_lane": expected_lane,
            "expected_route_mode": clean(case.get("expected_route_mode"))
            or "local_first",
            "expected_provider": clean(case.get("expected_provider")) or "norllama",
            "benchmark_assertions": [
                clean(item)
                for item in case.get("benchmark_assertions", [])
                if clean(item)
            ],
            "tags": [clean(item) for item in case.get("tags", []) if clean(item)],
        }
        return (
            f"{frontdoor.rstrip('/')}/v1/chat/completions",
            {
                "model": model,
                "stream": False,
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are executing a Norman local capability canary. "
                            "Return one compact JSON object only. Do not call tools. "
                            "Use this schema: case_id, suite_id, lane, route_mode, "
                            "provider, decision, confidence, evidence. The evidence "
                            "field must be an array of short strings grounded in the "
                            "provided case."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            instruction, sort_keys=True, ensure_ascii=True
                        ),
                    },
                ],
            },
            None,
            {"Content-Type": "application/json"},
            model,
        )
    if suite_id == "reranker":
        input_documents = input_spec.get("documents")
        document_rows = (
            [row for row in input_documents if isinstance(row, dict)]
            if isinstance(input_documents, list)
            else []
        )
        documents = [
            clean(row.get("text")) for row in document_rows if clean(row.get("text"))
        ]
        if not documents:
            documents = [
                "Norman route receipts include local worker attribution.",
                "Cloud escalation must be explicit and ledgered.",
                "Unrelated weather note.",
            ]
        query = clean(input_spec.get("query")) or prompt
        return (
            f"{frontdoor.rstrip('/')}/v1/rerank",
            {
                "query": query,
                "input_spec": input_spec,
                "documents": documents,
                "model": "BAAI/bge-reranker-v2-m3",
                "top_n": min(3, len(documents)),
            },
            None,
            {"Content-Type": "application/json"},
            "BAAI/bge-reranker-v2-m3",
        )
    if suite_id == "ocr":
        fixture_path = Path(clean(case.get("fixture_path")))
        if clean(case.get("fixture_path")):
            return (
                f"{frontdoor.rstrip('/')}/v1/ocr?format=json",
                {},
                fixture_path.read_bytes(),
                {
                    "Content-Type": clean(case.get("fixture_media_type"))
                    or "image/png",
                    "X-Filename": fixture_path.name,
                },
                "paddleocr:PP-OCRv6-small",
            )
        return (
            f"{frontdoor.rstrip('/')}/v1/ocr?format=json",
            {},
            base64.b64decode(OCR_SMOKE_PNG_BASE64),
            {
                "Content-Type": "image/png",
                "X-Filename": f"{clean(case.get('case_id')) or 'ocr-canary'}.png",
            },
            "paddleocr:PP-OCRv6-small",
        )
    if suite_id == ASR_SUITE and audio_fixture is not None:
        return (
            f"{frontdoor.rstrip('/')}/v1/audio/transcriptions",
            {},
            audio_fixture.read_bytes(),
            {
                "Content-Type": "audio/wav",
                "X-Filename": audio_fixture.name,
            },
            "faster-whisper:distil-large-v3",
        )
    return "", {}, None, {}, ""


def safety_text_from_input_spec(
    input_spec: dict[str, Any], *, fallback_prompt: str
) -> str:
    sections = [
        f"USER_INSTRUCTION: {clean(input_spec.get('user_instruction') or fallback_prompt)}",
    ]
    untrusted = clean(input_spec.get("untrusted_context"))
    if untrusted:
        sections.append(f"UNTRUSTED_CONTEXT: {untrusted}")
    proposed_tool_call = input_spec.get("proposed_tool_call")
    if isinstance(proposed_tool_call, dict) and proposed_tool_call:
        sections.append(
            "PROPOSED_TOOL_CALL: "
            + json.dumps(proposed_tool_call, sort_keys=True, ensure_ascii=True)
        )
    synthetic_secret = clean(input_spec.get("synthetic_secret"))
    if synthetic_secret:
        sections.append(f"SYNTHETIC_SECRET_PRESENT: {synthetic_secret}")
    return "\n".join(sections)


def is_case_passed(
    *,
    suite_id: str,
    payload: dict[str, Any],
    status: int,
) -> tuple[bool, str, str]:
    if status < 200 or status >= 300:
        return False, "error", f"http_{status}"
    if suite_id == "safety":
        schema = clean(payload.get("schema"))
        ok = schema == "norllama.safety-classification.v1"
        return ok, "complete" if ok else "empty", "" if ok else "missing_schema"
    if suite_id == "reranker":
        results = payload.get("results")
        ok = isinstance(results, list) and bool(results)
        return ok, "complete" if ok else "empty", "" if ok else "missing_results"
    if suite_id in CORE_AGENT_SUITES:
        text = response_text_preview(payload)
        ok = bool(text)
        return ok, "complete" if ok else "empty", "" if ok else "missing_response"
    if suite_id == "ocr":
        text = clean(payload.get("text") or payload.get("merged_text"))
        ok = clean(payload.get("status")) == "ok" and bool(text)
        return ok, "complete" if ok else "empty", "" if ok else "missing_text"
    if suite_id == ASR_SUITE:
        text = clean(payload.get("text") or payload.get("transcript"))
        ok = bool(text)
        return ok, "complete" if ok else "empty", "" if ok else "missing_transcript"
    return False, "error", "unsupported_suite"


def normalize_safety_label(value: Any) -> str:
    clean_value = clean(value).lower().replace("-", "_").replace(" ", "_")
    if not clean_value:
        return ""
    if clean_value in {"safe", "allowed", "allow", "low", "benign"}:
        return "benign"
    if "jailbreak" in clean_value or "prompt_injection" in clean_value:
        return "prompt_injection"
    if "secret" in clean_value:
        return "secret_request"
    if "credential" in clean_value:
        return "credential_exfiltration"
    if "privacy" in clean_value or "pii" in clean_value:
        return "privacy_sensitive"
    if "malware" in clean_value or "abuse" in clean_value:
        return "malware_or_abuse"
    return clean_value


def normalize_policy_action(value: Any) -> str:
    clean_value = clean(value).lower().replace("-", "_").replace(" ", "_")
    if clean_value in {"safe", "allowed", "allow"}:
        return "allow"
    if clean_value in {"deny", "denied", "blocked"}:
        return "block"
    return clean_value


def observed_safety_label(payload: dict[str, Any]) -> str:
    return normalize_safety_label(
        payload.get("label")
        or payload.get("category")
        or payload.get("risk_category")
        or payload.get("risk_level")
        or payload.get("classification")
    )


def observed_policy_action(payload: dict[str, Any]) -> str:
    return normalize_policy_action(
        payload.get("policy_action")
        or payload.get("action")
        or payload.get("decision")
        or payload.get("verdict")
    )


def reranker_top_index(payload: dict[str, Any]) -> int | None:
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return None
    first = results[0]
    if not isinstance(first, dict):
        return None
    try:
        return int(first.get("index"))
    except (TypeError, ValueError):
        return None


def reranker_top_source_id(
    *,
    payload: dict[str, Any],
    input_spec: dict[str, Any],
) -> str:
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return ""
    first = results[0]
    if not isinstance(first, dict):
        return ""
    direct = clean(
        first.get("source_id") or first.get("id") or first.get("document_id")
    )
    if direct:
        return direct
    index = reranker_top_index(payload)
    documents = input_spec.get("documents")
    if index is None or not isinstance(documents, list):
        return ""
    try:
        row = documents[index]
    except IndexError:
        return ""
    if not isinstance(row, dict):
        return ""
    return clean(row.get("source_id"))


def models_equivalent(requested_model: str, effective_model: str) -> bool:
    requested = clean(requested_model)
    effective = clean(effective_model)
    if not requested or not effective:
        return requested == effective
    if requested == effective:
        return True
    if requested.startswith("faster-whisper:"):
        return requested.removeprefix("faster-whisper:") == effective
    if effective.startswith("faster-whisper:"):
        return effective.removeprefix("faster-whisper:") == requested
    return False


def parse_json_object(text: str) -> dict[str, Any]:
    clean_text = clean(text)
    if not clean_text:
        return {}
    try:
        value = json.loads(clean_text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        start = clean_text.find("{")
        end = clean_text.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(clean_text[start : end + 1])
                return value if isinstance(value, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def core_agent_quality(
    *,
    case: dict[str, Any],
    suite_id: str,
    preview: str,
) -> tuple[bool, dict[str, Any]]:
    payload = parse_json_object(preview)
    expected_lane = clean(case.get("expected_lane")) or suite_id
    expected_route_mode = clean(case.get("expected_route_mode")) or "local_first"
    expected_provider = clean(case.get("expected_provider")) or "norllama"
    observed_case_id = clean(payload.get("case_id"))
    observed_suite_id = clean(payload.get("suite_id"))
    observed_lane = clean(payload.get("lane") or payload.get("route_lane"))
    observed_route_mode = clean(payload.get("route_mode") or payload.get("policy_mode"))
    observed_provider = clean(
        payload.get("provider") or payload.get("selected_provider")
    )
    decision = clean(payload.get("decision") or payload.get("verdict"))
    evidence = payload.get("evidence")
    evidence_passed = isinstance(evidence, list) and any(
        clean(item) for item in evidence
    )
    operation = CORE_AGENT_OPERATION.get(suite_id, "core_agent_decision")
    checks = {
        "json_parse": bool(payload),
        "case_id": observed_case_id == clean(case.get("case_id")),
        "suite_id": observed_suite_id == suite_id,
        "lane": observed_lane == expected_lane,
        "route_mode": observed_route_mode == expected_route_mode,
        "provider": observed_provider == expected_provider,
        "decision": bool(decision),
        "evidence": evidence_passed,
    }
    passed = all(checks.values())
    return passed, {
        "expected_lane": expected_lane,
        "observed_lane": observed_lane,
        "expected_route_mode": expected_route_mode,
        "observed_route_mode": observed_route_mode,
        "expected_provider": expected_provider,
        "observed_provider": observed_provider,
        "observed_decision": decision,
        "parsed_output": payload,
        "checks": checks,
        "required_operation_results": {operation: "pass" if passed else "fail"},
    }


def capability_quality(
    *,
    case: dict[str, Any],
    suite_id: str,
    payload: dict[str, Any],
    transport_passed: bool,
    expected_output_text: str,
    preview: str,
) -> tuple[bool, dict[str, Any]]:
    if not transport_passed:
        return False, {"reason": "transport_failed"}
    required_operations = [
        clean(item) for item in case.get("required_operations", []) if clean(item)
    ]
    if suite_id in CORE_AGENT_SUITES:
        return core_agent_quality(case=case, suite_id=suite_id, preview=preview)
    if suite_id == "safety":
        expected_label = normalize_safety_label(case.get("expected_label"))
        expected_action = normalize_policy_action(case.get("expected_policy_action"))
        label = observed_safety_label(payload)
        action = observed_policy_action(payload)
        label_passed = bool(expected_label and label and expected_label == label)
        action_passed = bool(expected_action and action and expected_action == action)
        raw_label = normalize_safety_label(
            payload.get("raw_label")
            or payload.get("classifier_label")
            or payload.get("model_label")
        )
        raw_action = normalize_policy_action(
            payload.get("raw_policy_action")
            or payload.get("classifier_policy_action")
            or payload.get("model_policy_action")
        )
        required_operation_results = {
            "classify_policy": "pass" if label_passed and action_passed else "fail"
        }
        return label_passed and action_passed, {
            "sensor": {
                "raw_label": raw_label,
                "raw_policy_action": raw_action,
                "sensor_passed": bool(
                    (not raw_label or raw_label == label)
                    and (not raw_action or raw_action == action)
                ),
            },
            "policy": {
                "normalized_label": label,
                "normalized_policy_action": action,
                "policy_passed": label_passed and action_passed,
            },
            "expected_label": expected_label,
            "observed_label": label,
            "expected_policy_action": expected_action,
            "observed_policy_action": action,
            "label_passed": label_passed,
            "policy_action_passed": action_passed,
            "required_operation_results": required_operation_results,
        }
    if suite_id == "reranker":
        input_spec = input_spec_for_case(case)
        expected_order = input_spec.get("expected_order")
        expected_top_source_id = (
            clean(expected_order[0])
            if isinstance(expected_order, list) and expected_order
            else ""
        )
        observed_top_source_id = reranker_top_source_id(
            payload=payload,
            input_spec=input_spec,
        )
        top_index = reranker_top_index(payload)
        source_id_passed = bool(
            expected_top_source_id
            and observed_top_source_id
            and expected_top_source_id == observed_top_source_id
        )
        top_index_passed = (
            top_index == 0 if not expected_top_source_id else source_id_passed
        )
        required_operation_results = {
            "rank_documents": "pass" if top_index_passed else "fail"
        }
        return top_index_passed, {
            "expected_top_source_id": expected_top_source_id,
            "observed_top_source_id": observed_top_source_id,
            "observed_top_index": top_index,
            "top_index_passed": top_index_passed,
            "required_operation_results": required_operation_results,
        }
    if expected_output_text:
        overlap = word_overlap_ratio(expected=expected_output_text, observed=preview)
        text_passed = overlap >= 0.8
        base_operation = "transcribe" if suite_id == ASR_SUITE else "extract_text"
        operation_results: dict[str, str] = {}
        for operation in required_operations or [base_operation]:
            if operation in {
                base_operation,
                "extract_visible_text",
            }:
                operation_results[operation] = "pass" if text_passed else "fail"
            else:
                operation_results[operation] = "not_evaluated"
        all_required_passed = bool(operation_results) and all(
            status == "pass" for status in operation_results.values()
        )
        return all_required_passed, {
            "expected_output_text": expected_output_text,
            "output_word_overlap": overlap,
            "threshold": 0.8,
            "required_operation_results": operation_results,
            "partial_text_passed": text_passed,
        }
    operation_results = {
        operation: "not_evaluated" for operation in required_operations
    }
    return False, {
        "reason": "transport_only_no_ground_truth",
        "required_operation_results": operation_results,
    }


def route_receipt_for_result(
    *,
    case: dict[str, Any],
    frontdoor: str,
    client_request_id: str,
    job_id: str,
    suite_id: str,
    requested_model: str,
    effective_model: str,
    route: dict[str, Any],
    headers: dict[str, str],
    worker: str,
    usage_bucket: str,
    usage: dict[str, int],
    output_shape: str,
    transport_passed: bool,
) -> dict[str, Any]:
    target_worker = target_worker_for_policy(clean(case.get("expected_worker_policy")))
    selected_worker = target_worker or worker
    peer_path = peer_path_from_response(
        route=route,
        headers=headers,
        frontdoor=frontdoor,
        worker=worker,
    )
    model_fallback = bool(
        requested_model
        and effective_model
        and not models_equivalent(requested_model, effective_model)
    )
    canonical_effective_model = (
        requested_model
        if requested_model
        and effective_model
        and models_equivalent(requested_model, effective_model)
        else effective_model or requested_model
    )
    worker_fallback = bool(target_worker and worker and target_worker != worker)
    fallback_reasons: list[str] = []
    if model_fallback:
        fallback_reasons.append(
            f"effective model {effective_model} differed from requested {requested_model}"
        )
    if worker_fallback:
        fallback_reasons.append(
            f"observed worker {worker} differed from target {target_worker}"
        )
    attempts = route.get("attempts") if isinstance(route.get("attempts"), list) else []
    if len(attempts) > 1:
        fallback_reasons.append(f"gateway recorded {len(attempts)} attempts")
    route_fallback_reason = clean(route.get("fallback_reason"))
    if route_fallback_reason:
        fallback_reasons.append(route_fallback_reason)
    fallback_reason = "; ".join(dict.fromkeys(fallback_reasons))
    fallback_used = bool(fallback_reason or route.get("fallback_used"))
    return normalize_route_receipt_for_completion_gate(
        {
            "status": "completed" if transport_passed else "failed",
            "request_id": client_request_id,
            "job_id": job_id,
            "phase": suite_id,
            "task_kind": suite_id,
            "selected_provider": "norllama",
            "selected_model": requested_model,
            "route_selected_model": requested_model,
            "requested_model": requested_model,
            "target_model": requested_model,
            "effective_runtime_model": canonical_effective_model,
            "model_override_used": False,
            "model_override_reason": "",
            "selected_worker": selected_worker,
            "target_worker": target_worker or selected_worker,
            "gateway_selected_worker": worker,
            "observed_worker": worker,
            "observed_worker_source": "gateway_response" if worker else "",
            "frontdoor": frontdoor.rstrip("/"),
            "peer_path": peer_path,
            "attempts": attempts,
            "route_reason": f"capability execution runner {suite_id} live smoke",
            "policy_mode": clean(case.get("expected_route_mode")) or "local_first",
            "cloud_proxy": bool(route.get("cloud_proxy")),
            "benchmark_packet_id": clean(case.get("suite_hash"))
            or clean(case.get("case_hash")),
            "benchmark_fresh": True,
            "benchmark_score": 1.0 if transport_passed else 0.0,
            "coverage_ratio": 1.0 if transport_passed else 0.0,
            "benchmark_gate": {
                "gate": "canary",
                "promotion_authoritative": False,
            },
            "transport_gate": {
                "gate": "canary",
                "promotion_authoritative": False,
            },
            "capability_gate": {
                "gate": "canary",
                "promotion_authoritative": False,
            },
            "promotion_authoritative": False,
            "capability_promotion_authoritative": False,
            "production_route_requires_capability_gate": True,
            "production_route_eligible": False,
            "benchmark_source": "capability_execution_runner",
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "total_tokens": usage["total_tokens"],
            "usage_bucket": usage_bucket,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "verifier_scope": "transport",
            "transport_verifier_result": "pass" if transport_passed else "fail",
            "capability_verifier_result": "not_run",
            "verifier_result": "pass" if transport_passed else "fail",
            "output_shape": output_shape,
            "completion_requested": True,
            "require_verifier_for_completion": True,
        }
    )


def dry_run_result(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": clean(case.get("case_id")),
        "suite_id": clean(case.get("suite_id")),
        **case_result_metadata(case),
        "title": clean(case.get("title")),
        "status": "planned_unexecuted",
        "transport_status": "not_run",
        "capability_status": "not_run",
        "overall_status": "planned_unexecuted",
        "execution_mode": "dry_run",
        "promotion_authoritative": False,
        "capability_gate": "unproven",
        "accepted": False,
        "transport_passed": False,
        "capability_quality_passed": False,
        "skip_reason": "dry_run_does_not_count",
        "expected_lane": clean(case.get("expected_lane")),
        "expected_provider": clean(case.get("expected_provider")),
        "observed_worker": "",
        "observed_worker_source": "",
        "usage_bucket": "",
        "local_tokens": 0,
        "cloud_llm_tokens": 0,
        "cloud_proxy_tokens": 0,
        "search_tokens": 0,
        "output_shape": "unknown",
        "receipt_audit": "not_run",
        "completion_gate": "not_run",
    }


def skipped_result(case: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **dry_run_result(case),
        "status": "skipped",
        "execution_mode": "live",
        "skip_reason": reason,
    }


def live_result(
    case: dict[str, Any],
    *,
    frontdoor: str,
    timeout_seconds: float,
    verify_tls: bool,
    audio_fixture: Path | None,
    audio_fixture_text: str = "",
    audio_fixture_id: str = "",
) -> dict[str, Any]:
    suite_id = clean(case.get("suite_id"))
    contract_failures = verify_case_contract(case)
    if contract_failures:
        return {
            **skipped_result(case, "case_contract_invalid"),
            "status": "failed",
            "transport_status": "not_run",
            "capability_status": "not_run",
            "overall_status": "case_contract_invalid",
            "failure_reason": ",".join(contract_failures),
            "contract_validation_failures": contract_failures,
        }
    if suite_id not in SUPPORTED_SUITES and not (
        suite_id == ASR_SUITE and audio_fixture is not None
    ):
        reason = "missing_audio_fixture" if suite_id == ASR_SUITE else "unsupported"
        return skipped_result(case, reason)
    endpoint, payload, body, headers, model = suite_endpoint_and_payload(
        case,
        frontdoor=frontdoor,
        audio_fixture=audio_fixture,
    )
    if not endpoint:
        return skipped_result(case, "unsupported")
    client_request_id = f"capability-runner:{uuid.uuid4().hex}"
    job_id = f"capability-runner-job:{uuid.uuid4().hex}"
    session_id = "capability-execution-runner"
    headers = {
        **headers,
        "X-Request-Id": client_request_id,
        "X-Norman-Job-Id": job_id,
        "X-Norman-Session": session_id,
        "X-Norman-Phase": suite_id,
        "X-Norman-Execution-Mode": "live",
        "X-Capability-Suite-Id": suite_id,
        "X-Capability-Case-Id": clean(case.get("case_id")),
    }
    started = time.perf_counter()
    try:
        response = http_json_request(
            "POST",
            endpoint,
            payload=payload if body is None else None,
            body=body,
            headers=headers,
            timeout_seconds=timeout_seconds,
            verify_tls=verify_tls,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        passed, output_shape, failure_reason = is_case_passed(
            suite_id=suite_id,
            payload=response.payload,
            status=response.status,
        )
        route = response_route(response.payload)
        worker, upstream = observed_worker(response.payload, response.headers)
        usage = response_usage(response.payload)
        usage_bucket = clean(route.get("usage_bucket")) or "offline_local"
        usage_observed = usage["total_tokens"] > 0
        work_units, work_unit_type = local_work_units(case, response.payload)
        preview = response_text_preview(response.payload)
        expected_output_text = (
            audio_fixture_text
            if suite_id == ASR_SUITE
            else clean(case.get("fixture_text"))
            if suite_id == "ocr"
            else ""
        )
        output_overlap = (
            word_overlap_ratio(expected=expected_output_text, observed=preview)
            if expected_output_text
            else 0.0
        )
        capability_quality_passed, capability_metrics = capability_quality(
            case=case,
            suite_id=suite_id,
            payload=response.payload,
            transport_passed=passed,
            expected_output_text=expected_output_text,
            preview=preview,
        )
        effective_model = clean(response.payload.get("model")) or model
        route_receipt = route_receipt_for_result(
            case=case,
            frontdoor=frontdoor,
            client_request_id=client_request_id,
            job_id=job_id,
            suite_id=suite_id,
            requested_model=model,
            effective_model=effective_model,
            route=route,
            headers=response.headers,
            worker=worker,
            usage_bucket=usage_bucket,
            usage=usage,
            output_shape=output_shape,
            transport_passed=passed,
        )
        route_receipt["capability_verifier_result"] = (
            "pass" if capability_quality_passed else "fail"
        )
        receipt_audit = audit_route_receipt(route_receipt)
        completion_gate_passed = receipt_completion_gate_passes(
            route_receipt,
            audit=receipt_audit,
            require_verifier=True,
        )
        status = (
            "passed"
            if passed and capability_quality_passed and completion_gate_passed
            else "capability_failed"
            if passed and completion_gate_passed
            else "failed"
        )
        fixture_path = (
            str(audio_fixture)
            if suite_id == ASR_SUITE
            else clean(case.get("fixture_path"))
        )
        fixture_hashes: list[str] = []
        if fixture_path and Path(fixture_path).exists():
            fixture_hashes.append(file_sha256(Path(fixture_path)))
        result = {
            "case_id": clean(case.get("case_id")),
            "suite_id": suite_id,
            **case_result_metadata(case),
            "title": clean(case.get("title")),
            "status": status,
            "transport_status": "pass" if passed else "fail",
            "capability_status": "pass" if capability_quality_passed else "fail",
            "overall_status": status,
            "transport_passed": passed,
            "capability_quality_passed": capability_quality_passed,
            "capability_metrics": capability_metrics,
            "transport_verifier_result": "pass" if passed else "fail",
            "capability_verifier_result": (
                "pass" if capability_quality_passed else "fail"
            ),
            "execution_mode": "live",
            "promotion_authoritative": False,
            "capability_gate": "canary_live" if status == "passed" else "failed",
            "accepted": status == "passed",
            "skip_reason": "",
            "failure_reason": failure_reason,
            "endpoint": endpoint,
            "http_status": response.status,
            "expected_lane": clean(case.get("expected_lane")),
            "expected_provider": clean(case.get("expected_provider")),
            "expected_worker_policy": clean(case.get("expected_worker_policy")),
            "scorer_version": CAPABILITY_SCORER_VERSION,
            "requested_model": model,
            "effective_runtime_model": clean(
                route_receipt.get("effective_runtime_model")
            ),
            "raw_effective_runtime_model": effective_model,
            "target_model": model,
            "fallback_used": bool(route_receipt.get("fallback_used")),
            "fallback_reason": clean(route_receipt.get("fallback_reason")),
            "target_worker": clean(route_receipt.get("target_worker")),
            "selected_worker": clean(route_receipt.get("selected_worker")),
            "observed_worker": worker,
            "observed_worker_source": "gateway_response" if worker else "",
            "upstream": upstream,
            "peer_path": route_receipt.get("peer_path")
            if isinstance(route_receipt.get("peer_path"), list)
            else [],
            "usage_bucket": usage_bucket,
            "usage_observed": usage_observed,
            "local_tokens": usage["total_tokens"]
            if usage_observed and usage_bucket == "offline_local"
            else None,
            "local_work_units": work_units,
            "local_work_unit_type": work_unit_type,
            "cloud_llm_tokens": usage["total_tokens"]
            if usage_bucket in {"openai_codex", "bedrock_amazon", "other_cloud"}
            else 0,
            "cloud_proxy_tokens": usage["total_tokens"]
            if bool(route.get("cloud_proxy"))
            else 0,
            "search_tokens": usage["total_tokens"]
            if usage_bucket == "perplexity_web"
            else 0,
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "total_tokens": usage["total_tokens"],
            "cloud_proxy": bool(route.get("cloud_proxy")),
            "output_shape": output_shape,
            "observed_output": response.payload,
            "transcript_preview": preview if suite_id == ASR_SUITE else "",
            "expected_transcript": expected_output_text
            if suite_id == ASR_SUITE
            else "",
            "expected_output_text": expected_output_text,
            "transcript_word_overlap": output_overlap if suite_id == ASR_SUITE else 0.0,
            "output_word_overlap": output_overlap,
            "output_preview": preview,
            "fixture_path": fixture_path,
            "fixture_id": audio_fixture_id
            if suite_id == ASR_SUITE
            else clean(case.get("fixture_id")),
            "fixture_sha256": fixture_hashes[0] if fixture_hashes else "",
            "input_artifact_hashes": fixture_hashes,
            "receipt_audit": receipt_audit,
            "completion_gate": {
                "gate_passed": completion_gate_passed,
                "status": "pass" if completion_gate_passed else "fail",
            },
            "route_receipt": route_receipt,
            "elapsed_ms": elapsed_ms,
            "request_id": client_request_id,
            "client_request_id": client_request_id,
            "gateway_request_id": clean(
                response.headers.get("x-request-id")
                or response.headers.get("x-norllama-request-id")
            ),
            "job_id": job_id,
            "session": session_id,
        }
        instance = execution_instance_payload(result)
        result["execution_instance"] = instance
        result["execution_input_hash"] = sha256_text(instance)
        return result
    except (TimeoutError, socket.timeout) as exc:
        return {
            **skipped_result(case, "timeout"),
            "status": "failed",
            "output_shape": "timeout",
            "failure_reason": str(exc),
        }
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        return {
            **skipped_result(case, "request_error"),
            "status": "failed",
            "output_shape": "error",
            "failure_reason": str(exc),
        }


def execute_cases(
    cases: list[dict[str, Any]],
    *,
    live: bool,
    frontdoor: str,
    timeout_seconds: float,
    verify_tls: bool,
    audio_fixture: Path | None = None,
    audio_fixture_text: str = "",
    audio_fixture_id: str = "",
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in cases:
        if live:
            results.append(
                live_result(
                    case,
                    frontdoor=frontdoor,
                    timeout_seconds=timeout_seconds,
                    verify_tls=verify_tls,
                    audio_fixture=audio_fixture,
                    audio_fixture_text=audio_fixture_text,
                    audio_fixture_id=audio_fixture_id,
                )
            )
        else:
            results.append(dry_run_result(case))
    return results


def suite_counts(results: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for result in results:
        suite_id = clean(result.get("suite_id"))
        row = counts.setdefault(
            suite_id,
            {
                "selected": 0,
                "passed": 0,
                "capability_failed": 0,
                "failed": 0,
                "skipped": 0,
                "planned_unexecuted": 0,
                "live": 0,
                "dry_run": 0,
            },
        )
        row["selected"] += 1
        if result.get("status") == "passed":
            row["passed"] += 1
        elif result.get("status") == "capability_failed":
            row["capability_failed"] += 1
        elif result.get("status") == "skipped":
            row["skipped"] += 1
        elif result.get("status") == "planned_unexecuted":
            row["planned_unexecuted"] += 1
        else:
            row["failed"] += 1
        if result.get("execution_mode") == "live":
            row["live"] += 1
        if result.get("execution_mode") == "dry_run":
            row["dry_run"] += 1
    return counts


def build_result_packet(
    *,
    manifest: dict[str, Any],
    selected_cases: list[dict[str, Any]],
    results: list[dict[str, Any]],
    frontdoor: str,
    live: bool,
    packet_id: str | None = None,
    fixtures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    passed = sum(1 for result in results if result.get("status") == "passed")
    capability_failed = sum(
        1 for result in results if result.get("status") == "capability_failed"
    )
    failed = sum(
        1
        for result in results
        if result.get("status") in {"failed", "capability_failed"}
    )
    skipped = sum(1 for result in results if result.get("status") == "skipped")
    dry_run = sum(1 for result in results if result.get("execution_mode") == "dry_run")
    live_count = sum(1 for result in results if result.get("execution_mode") == "live")
    transport_passed = sum(1 for result in results if result.get("transport_passed"))
    capability_quality_passed = sum(
        1 for result in results if result.get("capability_quality_passed")
    )
    local_tokens = sum(count_int(result.get("local_tokens")) for result in results)
    cloud_llm_tokens = sum(
        count_int(result.get("cloud_llm_tokens")) for result in results
    )
    cloud_proxy_tokens = sum(
        count_int(result.get("cloud_proxy_tokens")) for result in results
    )
    search_tokens = sum(count_int(result.get("search_tokens")) for result in results)
    work_units: dict[str, int] = {}
    for result in results:
        unit_type = clean(result.get("local_work_unit_type"))
        if unit_type:
            work_units[unit_type] = work_units.get(unit_type, 0) + count_int(
                result.get("local_work_units")
            )
    all_passed = bool(results) and passed == len(results)
    return {
        "schema": RESULT_SCHEMA,
        "packet_id": packet_id or f"capability-execution-results-{utc_now()}",
        "generated_at": utc_now(),
        "source_manifest_id": clean(manifest.get("manifest_id")),
        "source_manifest_schema": clean(manifest.get("schema")),
        "frontdoor": frontdoor,
        "execution_mode": "live" if live else "dry_run",
        "promotion_authoritative": False,
        "fixtures": fixtures or [],
        "capability_gate": {
            "gate": "canary_live" if live and all_passed else "unproven",
            "promotion_authoritative": False,
            "dry_run_shadow_does_not_count": True,
            "transport_backing_is_not_capability_backing": True,
        },
        "selected_case_count": len(selected_cases),
        "result_count": len(results),
        "passed_count": passed,
        "capability_failed_count": capability_failed,
        "failed_count": failed,
        "skipped_count": skipped,
        "live_count": live_count,
        "dry_run_count": dry_run,
        "transport_passed_count": transport_passed,
        "capability_quality_passed_count": capability_quality_passed,
        "suite_counts": suite_counts(results),
        "usage_totals": {
            "local_tokens": local_tokens,
            "cloud_llm_tokens": cloud_llm_tokens,
            "cloud_proxy_tokens": cloud_proxy_tokens,
            "search_tokens": search_tokens,
            "local_work_units": work_units,
        },
        "proof_notes": [
            "This packet executes capability cases but is not promotion-authoritative.",
            "Dry-run rows, skipped rows, and fixture-missing rows do not count as live proof.",
            "Current smoke fixtures prove gateway reachability, not full capability quality.",
        ],
        "results": results,
    }


def manifest_case_index(
    manifest: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (clean(case.get("suite_id")), clean(case.get("case_id"))): case
        for case in manifest_cases(manifest)
    }


def _completion_gate_passed(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value.get("gate_passed") or value.get("pass"))
    return clean(value).lower() == "pass"


def _receipt_audit_passed(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value.get("pass")) and clean(value.get("status")).lower() == "pass"
    return clean(value).lower() == "pass"


def recomputed_packet_counts(results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for result in results if result.get("status") == "passed")
    capability_failed = sum(
        1 for result in results if result.get("status") == "capability_failed"
    )
    failed = sum(
        1
        for result in results
        if result.get("status") in {"failed", "capability_failed"}
    )
    skipped = sum(1 for result in results if result.get("status") == "skipped")
    dry_run = sum(1 for result in results if result.get("execution_mode") == "dry_run")
    live_count = sum(1 for result in results if result.get("execution_mode") == "live")
    transport_passed = sum(1 for result in results if result.get("transport_passed"))
    capability_quality_passed = sum(
        1 for result in results if result.get("capability_quality_passed")
    )
    work_units: dict[str, int] = {}
    for result in results:
        unit_type = clean(result.get("local_work_unit_type"))
        if unit_type:
            work_units[unit_type] = work_units.get(unit_type, 0) + count_int(
                result.get("local_work_units")
            )
    return {
        "selected_case_count": len(results),
        "result_count": len(results),
        "passed_count": passed,
        "capability_failed_count": capability_failed,
        "failed_count": failed,
        "skipped_count": skipped,
        "live_count": live_count,
        "dry_run_count": dry_run,
        "transport_passed_count": transport_passed,
        "capability_quality_passed_count": capability_quality_passed,
        "suite_counts": suite_counts(results),
        "usage_totals": {
            "local_tokens": sum(
                count_int(result.get("local_tokens")) for result in results
            ),
            "cloud_llm_tokens": sum(
                count_int(result.get("cloud_llm_tokens")) for result in results
            ),
            "cloud_proxy_tokens": sum(
                count_int(result.get("cloud_proxy_tokens")) for result in results
            ),
            "search_tokens": sum(
                count_int(result.get("search_tokens")) for result in results
            ),
            "local_work_units": work_units,
        },
    }


def _json_equal(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, default=str) == json.dumps(
        right, sort_keys=True, default=str
    )


def packet_fixture_index(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fixtures = packet.get("fixtures")
    if not isinstance(fixtures, list):
        return {}
    return {
        clean(fixture.get("fixture_id")): fixture
        for fixture in fixtures
        if isinstance(fixture, dict) and clean(fixture.get("fixture_id"))
    }


def validate_result_packet(
    packet: dict[str, Any],
    *,
    manifest: dict[str, Any] | None = None,
) -> list[str]:
    failures: list[str] = []
    case_index = manifest_case_index(manifest) if isinstance(manifest, dict) else {}
    fixture_index = packet_fixture_index(packet)
    results = [row for row in packet.get("results") or [] if isinstance(row, dict)]
    if clean(packet.get("schema")) != RESULT_SCHEMA:
        failures.append("invalid_schema")
    if packet.get("promotion_authoritative") is not False:
        failures.append("result_packet_must_not_be_promotion_authoritative")
    expected_counts = recomputed_packet_counts(results)
    for key in (
        "selected_case_count",
        "result_count",
        "passed_count",
        "capability_failed_count",
        "failed_count",
        "skipped_count",
        "live_count",
        "dry_run_count",
        "transport_passed_count",
        "capability_quality_passed_count",
    ):
        if count_int(packet.get(key)) != count_int(expected_counts[key]):
            failures.append(f"packet_{key}_mismatch")
    if not _json_equal(
        packet.get("suite_counts") or {}, expected_counts["suite_counts"]
    ):
        failures.append("packet_suite_counts_mismatch")
    if not _json_equal(
        packet.get("usage_totals") or {}, expected_counts["usage_totals"]
    ):
        failures.append("packet_usage_totals_mismatch")
    gate = packet.get("capability_gate")
    if not isinstance(gate, dict):
        failures.append("packet_missing_capability_gate")
    else:
        if gate.get("promotion_authoritative") is not False:
            failures.append("packet_capability_gate_promotion_authoritative")
        if clean(gate.get("gate")) == "production":
            failures.append("packet_capability_gate_must_not_be_production")
        all_passed = bool(results) and expected_counts["passed_count"] == len(results)
        expected_gate = (
            "canary_live"
            if clean(packet.get("execution_mode")) == "live" and all_passed
            else "unproven"
        )
        if clean(gate.get("gate")) != expected_gate:
            failures.append("packet_capability_gate_mismatch")
    for index, result in enumerate(results):
        status = clean(result.get("status"))
        if status not in {
            "passed",
            "failed",
            "capability_failed",
            "skipped",
            "planned_unexecuted",
        }:
            failures.append(f"result_{index}:invalid_status")
        transport_status = clean(result.get("transport_status"))
        capability_status = clean(result.get("capability_status"))
        if result.get("execution_mode") == "live":
            if transport_status not in {"pass", "fail", "not_run"}:
                failures.append(f"result_{index}:invalid_transport_status")
            if capability_status not in {"pass", "fail", "not_run"}:
                failures.append(f"result_{index}:invalid_capability_status")
        if status == "passed" and (
            result.get("transport_passed") is not True
            or result.get("capability_quality_passed") is not True
        ):
            failures.append(f"result_{index}:passed_without_capability_quality")
        if status == "capability_failed" and result.get("transport_passed") is not True:
            failures.append(f"result_{index}:capability_failed_without_transport")
        if result.get("promotion_authoritative") is not False:
            failures.append(f"result_{index}:promotion_authoritative")
        if result.get("execution_mode") == "dry_run" and result.get("status") in {
            "passed",
            "failed",
        }:
            failures.append(f"result_{index}:dry_run_claimed_execution")
        if result.get("execution_mode") == "dry_run":
            continue
        if status == "passed" and not clean(result.get("observed_worker")):
            failures.append(f"result_{index}:missing_observed_worker")
        if status == "passed" and clean(result.get("observed_worker_source")) != (
            "gateway_response"
        ):
            failures.append(f"result_{index}:observed_worker_not_gateway_response")
        if result.get("cloud_proxy"):
            failures.append(f"result_{index}:cloud_proxy_used")
        if any(
            count_int(result.get(key)) > 0
            for key in ("cloud_llm_tokens", "cloud_proxy_tokens", "search_tokens")
        ):
            failures.append(f"result_{index}:unexpected_cloud_usage")
        if status == "passed" and not _receipt_audit_passed(
            result.get("receipt_audit")
        ):
            failures.append(f"result_{index}:receipt_audit_not_passed")
        if status == "passed" and not _completion_gate_passed(
            result.get("completion_gate")
        ):
            failures.append(f"result_{index}:completion_gate_not_passed")
        if status == "passed" and clean(result.get("output_shape")) != "complete":
            failures.append(f"result_{index}:output_shape_not_complete")
        if result.get("usage_observed") is False and result.get("local_tokens") not in {
            None,
            0,
        }:
            failures.append(f"result_{index}:synthetic_local_tokens")
        if status in {"passed", "capability_failed"}:
            if not clean(result.get("request_id")):
                failures.append(f"result_{index}:missing_request_id")
            if not clean(result.get("job_id")):
                failures.append(f"result_{index}:missing_job_id")
            if not clean(result.get("input_hash")):
                failures.append(f"result_{index}:missing_input_hash")
            if not clean(result.get("case_hash")):
                failures.append(f"result_{index}:missing_case_hash")
            if not clean(result.get("gateway_request_id")):
                failures.append(f"result_{index}:missing_gateway_request_id")
            if not isinstance(result.get("observed_output"), dict):
                failures.append(f"result_{index}:missing_observed_output")
        case_key = (clean(result.get("suite_id")), clean(result.get("case_id")))
        expected = case_index.get(case_key)
        if expected:
            if clean(result.get("case_hash")) != clean(expected.get("case_hash")):
                failures.append(f"result_{index}:case_hash_mismatch")
            if clean(result.get("suite_hash")) != clean(expected.get("suite_hash")):
                failures.append(f"result_{index}:suite_hash_mismatch")
            if clean(result.get("input_hash")) != clean(expected.get("input_hash")):
                failures.append(f"result_{index}:input_hash_mismatch")
            if clean(result.get("expected_provider")) != clean(
                expected.get("expected_provider")
            ):
                failures.append(f"result_{index}:expected_provider_mismatch")
            expected_lane = clean(expected.get("expected_lane"))
            if expected_lane and clean(result.get("expected_lane")) != expected_lane:
                failures.append(f"result_{index}:expected_lane_mismatch")
            expected_worker = target_worker_for_policy(
                clean(expected.get("expected_worker_policy"))
            )
            observed_worker = clean(result.get("observed_worker"))
            if (
                status == "passed"
                and expected_worker
                and observed_worker
                and expected_worker != observed_worker
                and not result.get("fallback_used")
            ):
                failures.append(f"result_{index}:worker_mismatch_without_fallback")
        elif case_index:
            failures.append(f"result_{index}:unknown_manifest_case")
        fixture_hash = clean(result.get("fixture_sha256"))
        artifact_hashes = [
            clean(item)
            for item in result.get("input_artifact_hashes", [])
            if clean(item)
        ]
        if fixture_hash and fixture_hash not in artifact_hashes:
            failures.append(f"result_{index}:fixture_hash_not_in_artifacts")
        fixture_id = clean(result.get("fixture_id"))
        if fixture_id and fixture_id in fixture_index:
            packet_fixture_hash = clean(fixture_index[fixture_id].get("sha256"))
            if packet_fixture_hash and fixture_hash != packet_fixture_hash:
                failures.append(f"result_{index}:packet_fixture_hash_mismatch")
        expected_instance = execution_instance_payload(result)
        stored_instance = result.get("execution_instance")
        if isinstance(stored_instance, dict) and not _json_equal(
            stored_instance, expected_instance
        ):
            failures.append(f"result_{index}:execution_instance_mismatch")
        if clean(result.get("execution_input_hash")) and clean(
            result.get("execution_input_hash")
        ) != sha256_text(expected_instance):
            failures.append(f"result_{index}:execution_input_hash_mismatch")
        route_receipt = result.get("route_receipt")
        if status in {"passed", "capability_failed"} and not isinstance(
            route_receipt, dict
        ):
            failures.append(f"result_{index}:missing_route_receipt")
            continue
        if isinstance(route_receipt, dict):
            recomputed_audit = audit_route_receipt(route_receipt)
            recomputed_gate = receipt_completion_gate_passes(
                route_receipt,
                audit=recomputed_audit,
                require_verifier=True,
            )
            if _receipt_audit_passed(result.get("receipt_audit")) != bool(
                recomputed_audit.get("pass")
            ):
                failures.append(f"result_{index}:receipt_audit_recompute_mismatch")
            if _completion_gate_passed(result.get("completion_gate")) != bool(
                recomputed_gate
            ):
                failures.append(f"result_{index}:completion_gate_recompute_mismatch")
            if status in {"passed", "capability_failed"} and not recomputed_audit.get(
                "pass"
            ):
                failures.append(f"result_{index}:receipt_audit_not_passed")
            if status in {"passed", "capability_failed"} and not recomputed_gate:
                failures.append(f"result_{index}:completion_gate_not_passed")
            if clean(route_receipt.get("selected_provider")) != "norllama":
                failures.append(f"result_{index}:route_receipt_provider_mismatch")
            if clean(route_receipt.get("requested_model")) != clean(
                result.get("requested_model")
            ):
                failures.append(f"result_{index}:requested_model_mismatch")
            if clean(route_receipt.get("target_model")) != clean(
                result.get("target_model")
            ):
                failures.append(f"result_{index}:target_model_mismatch")
            if clean(route_receipt.get("effective_runtime_model")) != clean(
                result.get("effective_runtime_model")
            ):
                failures.append(f"result_{index}:effective_model_mismatch")
            if clean(route_receipt.get("observed_worker")) != clean(
                result.get("observed_worker")
            ):
                failures.append(f"result_{index}:observed_worker_mismatch")
            if clean(route_receipt.get("output_shape")) != clean(
                result.get("output_shape")
            ):
                failures.append(f"result_{index}:output_shape_mismatch")
            if clean(route_receipt.get("usage_bucket")) != clean(
                result.get("usage_bucket")
            ):
                failures.append(f"result_{index}:usage_bucket_mismatch")
            if route_receipt.get("cloud_proxy"):
                failures.append(f"result_{index}:route_receipt_cloud_proxy_used")
            if (
                route_receipt.get("production_route_requires_capability_gate") is True
                and route_receipt.get("production_route_eligible") is not False
            ):
                failures.append(
                    f"result_{index}:production_eligible_without_capability"
                )
        payload = (
            result.get("observed_output")
            if isinstance(result.get("observed_output"), dict)
            else {}
        )
        if payload:
            recomputed_transport, recomputed_shape, _reason = is_case_passed(
                suite_id=clean(result.get("suite_id")),
                payload=payload,
                status=count_int(result.get("http_status")),
            )
            if result.get("transport_passed") is not recomputed_transport:
                failures.append(f"result_{index}:transport_recompute_mismatch")
            if clean(result.get("output_shape")) != recomputed_shape:
                failures.append(f"result_{index}:output_shape_recompute_mismatch")
            expected_output_text = clean(
                result.get("expected_output_text") or result.get("expected_transcript")
            )
            recomputed_quality, recomputed_metrics = capability_quality(
                case=expected or result,
                suite_id=clean(result.get("suite_id")),
                payload=payload,
                transport_passed=recomputed_transport,
                expected_output_text=expected_output_text,
                preview=clean(result.get("output_preview")),
            )
            if result.get("capability_quality_passed") is not recomputed_quality:
                failures.append(f"result_{index}:capability_quality_recompute_mismatch")
            if clean(result.get("capability_verifier_result")) != (
                "pass" if recomputed_quality else "fail"
            ):
                failures.append(f"result_{index}:capability_verifier_mismatch")
            if not _json_equal(
                result.get("capability_metrics") or {},
                recomputed_metrics,
            ):
                failures.append(f"result_{index}:capability_metrics_mismatch")
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--frontdoor", default=DEFAULT_FRONTDOOR)
    parser.add_argument("--suite", action="append", default=[])
    parser.add_argument("--limit-per-suite", type=int, default=1)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--verify-tls", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--audio-fixture", type=Path)
    parser.add_argument("--generate-asr-fixture", action="store_true")
    parser.add_argument("--asr-fixture-output", type=Path, default=DEFAULT_ASR_FIXTURE)
    parser.add_argument("--asr-fixture-text", default=DEFAULT_ASR_FIXTURE_TEXT)
    parser.add_argument("--generate-ocr-fixtures", action="store_true")
    parser.add_argument("--ocr-fixture-dir", type=Path, default=DEFAULT_OCR_FIXTURE_DIR)
    parser.add_argument("--ocr-font", type=Path, default=DEFAULT_OCR_FONT)
    parser.add_argument("--packet-id", default="")
    parser.add_argument("--allow-failures", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_manifest(args.manifest)
    fixtures: list[dict[str, Any]] = []
    audio_fixture = args.audio_fixture
    if args.generate_asr_fixture:
        fixture = generate_asr_fixture(
            output=args.asr_fixture_output,
            text=args.asr_fixture_text,
        )
        fixtures.append(fixture)
        audio_fixture = args.asr_fixture_output
        audio_fixture_text = clean(fixture.get("text"))
        audio_fixture_id = clean(fixture.get("fixture_id"))
    elif audio_fixture is not None:
        audio_fixture_text = ""
        audio_fixture_id = "asr-operator-supplied"
        fixtures.append(
            {
                "fixture_id": "asr-operator-supplied",
                "suite_id": ASR_SUITE,
                "path": str(audio_fixture),
                "generator": "operator_supplied",
                "text": "",
                "media_type": "audio/wav",
                "generated": False,
                "size_bytes": audio_fixture.stat().st_size
                if audio_fixture.exists()
                else 0,
            }
        )
    else:
        audio_fixture_text = ""
        audio_fixture_id = ""
    if args.generate_ocr_fixtures:
        fixtures.extend(
            generate_ocr_fixtures(
                output_dir=args.ocr_fixture_dir,
                font_path=args.ocr_font,
            )
        )
    suites = {clean(item) for item in args.suite if clean(item)} or None
    selected = select_cases(
        manifest,
        suites=suites,
        limit_per_suite=max(0, args.limit_per_suite),
    )
    selected = attach_suite_fixtures(
        selected,
        suite_id="ocr",
        fixtures=[fixture for fixture in fixtures if fixture.get("suite_id") == "ocr"],
    )
    results = execute_cases(
        selected,
        live=bool(args.live),
        frontdoor=args.frontdoor,
        timeout_seconds=max(1.0, float(args.timeout_seconds)),
        verify_tls=bool(args.verify_tls),
        audio_fixture=audio_fixture,
        audio_fixture_text=audio_fixture_text,
        audio_fixture_id=audio_fixture_id,
    )
    packet = build_result_packet(
        manifest=manifest,
        selected_cases=selected,
        results=results,
        frontdoor=args.frontdoor,
        live=bool(args.live),
        packet_id=args.packet_id or None,
        fixtures=fixtures,
    )
    failures = validate_result_packet(packet, manifest=manifest)
    packet["validation_failures"] = failures
    write_json_document(packet, args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "packet_id": packet["packet_id"],
                "execution_mode": packet["execution_mode"],
                "selected_case_count": packet["selected_case_count"],
                "passed_count": packet["passed_count"],
                "failed_count": packet["failed_count"],
                "skipped_count": packet["skipped_count"],
                "transport_passed_count": packet["transport_passed_count"],
                "capability_quality_passed_count": packet[
                    "capability_quality_passed_count"
                ],
                "validation_failures": failures,
            },
            indent=2,
            sort_keys=True,
        )
    )
    if failures and not args.allow_failures:
        return 2
    if packet["failed_count"] and args.live and not args.allow_failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
