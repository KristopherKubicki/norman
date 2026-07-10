#!/usr/bin/env python3
from __future__ import annotations

import argparse
import email.policy
import html
import json
import mimetypes
import os
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 18151
DEFAULT_TIMEOUT_S = 120
DEFAULT_OLLAMA_BASES = ("http://127.0.0.1:11434",)
DEFAULT_DS4_BASES = ("http://127.0.0.1:8002",)
DEFAULT_DS4_BASE = DEFAULT_DS4_BASES[0]
DEFAULT_MEDIA_BASES = ("http://127.0.0.1:8100",)
DEFAULT_TRANSCRIBE_BASES = ("http://127.0.0.1:8097",)
DEFAULT_OCR_BASES = ("http://127.0.0.1:8098",)
DEFAULT_RERANK_BASES = ("http://127.0.0.1:8102",)
DEFAULT_SAFETY_BASES = ("http://127.0.0.1:8103",)
DEFAULT_IMAGE_BASES = ("http://127.0.0.1:7860",)
DEFAULT_MEDIA_KEY_FILE = str(Path.home() / ".config/norllama/media/api_key")
DEFAULT_MEDIA_KEY_DIR = str(Path.home() / ".config/norllama/media/keys")
DEFAULT_TRANSCRIBE_KEY_FILE = str(Path.home() / ".config/norllama/transcribe/api_key")
DEFAULT_TRANSCRIBE_KEY_DIR = str(Path.home() / ".config/norllama/transcribe/keys")
DEFAULT_OCR_KEY_FILE = "/etc/spark-ocr/api_key"
DEFAULT_OCR_KEY_DIR = str(Path.home() / ".config/norllama/ocr/keys")
DEFAULT_RERANK_KEY_FILE = "/etc/spark-rerank/api_key"
DEFAULT_RERANK_KEY_DIR = str(Path.home() / ".config/norllama/rerank/keys")
DEFAULT_SAFETY_KEY_FILE = "/etc/spark-safety/api_key"
DEFAULT_SAFETY_KEY_DIR = str(Path.home() / ".config/norllama/safety/keys")
DEFAULT_IMAGE_KEY_FILE = str(Path.home() / ".config/norllama/image/api_key")
DEFAULT_IMAGE_KEY_DIR = str(Path.home() / ".config/norllama/image/keys")
DEFAULT_PEER_BASES: tuple[str, ...] = ()
DEFAULT_DISCOVERY_ENV_FILES = (
    "/etc/net-agents/uplink.env",
    "/etc/net-agents/cloudagent.env",
    "/etc/net-agents/networking.env",
)
DEFAULT_PACKET_ROOTS = (
    Path(__file__).resolve().parent,
    Path.home() / "networking/radio/phobos_hunt",
    Path("/home/debian/networking/radio/phobos_hunt"),
)
DEFAULT_BENCHMARK_PACKET_PATHS = tuple(
    str(root / "evidence" / "norllama_benchmark_packet_latest" / "packet.json")
    for root in DEFAULT_PACKET_ROOTS
)
DEFAULT_PREFLIGHT_PACKET_PATHS = tuple(
    str(root / "evidence" / "norllama_superhuman_preflight_latest" / "packet.json")
    for root in DEFAULT_PACKET_ROOTS
)
DEFAULT_MODEL_CACHE_TTL_S = 15
DEFAULT_INVENTORY_TIMEOUT_S = 3
DEFAULT_ACTIVITY_LIMIT = 200
DEFAULT_TOOL_ACTIVITY_LIMIT = 1000
DEFAULT_PEER_TIMEOUT_S = 1.0
DEFAULT_MAX_PEER_HOPS = 1
DEFAULT_PREFETCH_JOB_TTL_S = 3600
DEFAULT_PREFETCH_JOB_LIMIT = 100
DEFAULT_EMBEDDING_MODEL = os.getenv("NORLLAMA_DEFAULT_EMBEDDING_MODEL", "bge-m3:latest")
BGE_RERANKER_MODEL = os.getenv(
    "NORLLAMA_NATIVE_RERANK_MODEL", "BAAI/bge-reranker-v2-m3"
)
DEFAULT_RERANK_MODEL = os.getenv("NORLLAMA_DEFAULT_RERANK_MODEL", BGE_RERANKER_MODEL)
QWEN3GUARD_MODEL = os.getenv(
    "NORLLAMA_DEFAULT_SAFETY_MODEL", "Qwen/Qwen3Guard-Stream-0.6B"
)
QWEN36_ROUTER_MODEL = "qwen3.6:35b-a3b-q4_K_M"
QWEN36_CODE_MODEL = "qwen3.6:27b"
QWEN35_JUDGE_MODEL = "qwen3.5:122b-a10b-q4_K_M"
QWEN3_VL_MODEL = "qwen3-vl:30b-a3b-instruct-q4_K_M"
PREFERRED_UI_CHAT_MODEL = os.getenv("NORLLAMA_UI_DEFAULT_MODEL", QWEN36_ROUTER_MODEL)
USER_AGENT = "norllama-gateway/0.1"
GATEWAY_VERSION = os.getenv("NORLLAMA_GATEWAY_VERSION", "0.1.20260702")
GATEWAY_BUILD = os.getenv("NORLLAMA_GATEWAY_BUILD", "worker-frontdoor-unified")
NANOSECONDS = 1_000_000_000.0
HIDDEN_MODEL_IDS = {
    "karanchopda333/whisper:latest",
    "sendmeaiohyeah/whisper-large-v2:latest",
    "yangzhang0323/qwen3-asr-0.6b:q8_0",
}
PRIORITY_LEVELS = {"high", "normal", "background"}
WARM_POLICY_LANES = (
    "planner",
    "scout",
    "summarizer",
    "coder",
    "filter",
    "verifier",
    "canary",
)
WARM_POLICY_CONTRACT_LANES = {
    "chat": ("planner", "scout", "summarizer", "verifier"),
    "general_chat": ("planner", "scout", "summarizer", "verifier"),
    "default": ("planner", "scout", "summarizer", "verifier"),
    "vision_grounding": ("scout", "verifier"),
    "vision": ("scout", "verifier"),
    "grounding": ("scout", "verifier"),
    "doc_parse": ("scout", "summarizer"),
    "document_parse": ("scout", "summarizer"),
    "ocr_parse": ("scout", "summarizer"),
    "embed": ("filter",),
    "embedding": ("filter",),
    "embeddings": ("filter",),
    "vectorize": ("filter",),
    "dense_embed": ("filter",),
    "rerank": ("filter",),
    "reranker": ("filter",),
    "rank": ("filter",),
    "reranking": ("filter",),
    "hybrid_retrieve": ("scout", "filter"),
    "retrieve": ("scout", "filter"),
    "hybrid_search": ("scout", "filter"),
    "semantic_search": ("scout", "filter"),
    "safety_privacy_classify": ("filter", "verifier"),
    "safety_classify": ("filter", "verifier"),
    "privacy_classify": ("filter", "verifier"),
    "image_generate": ("scout", "planner"),
    "stable_diffusion": ("scout", "planner"),
    "entity_event_extract": ("scout", "summarizer", "planner"),
    "entity_extract": ("scout", "summarizer", "planner"),
    "event_extract": ("scout", "summarizer", "planner"),
    "ops_anomaly": ("scout", "verifier"),
    "anomaly_detect": ("scout", "verifier"),
    "ops_anomaly_detect": ("scout", "verifier"),
    "code_risk": ("coder", "verifier"),
    "patch_risk": ("coder", "verifier"),
    "test_selection": ("coder", "verifier"),
    "change_impact": ("coder", "verifier"),
}
WARM_POLICY_READY_STATUSES = {
    "accepted",
    "benchmark_backed",
    "benchmark_backed_routable",
    "indirect_benchmark",
    "live_tool_lane",
    "ok",
    "partial_live_policy",
    "passed",
    "preferred",
    "recommended",
    "routable_live_policy",
    "selected",
}
WARM_POLICY_CANARY_STATUSES = {
    "experimental",
    "observe_only",
    "pending_benchmark",
}
WARM_POLICY_TOOL_ONLY_DISPATCHES = {
    "embedding_proxy",
    "hybrid_pipeline",
    "media_proxy",
    "ocr_proxy",
    "image_generation_proxy",
    "rerank_proxy",
    "safety_proxy",
    "transcribe_proxy",
}
WARM_POLICY_OBSERVE_ONLY_MODEL_NEEDLES = (
    "devstral",
    "gpt-oss:120b",
    "llama4:",
    "nemotron",
    "openfugu",
)
LIVE_POLICY_OVERRIDE_REASON = (
    "Live Qwen-first Spark policy overrides stale Gemma-era benchmark defaults until "
    "the next Uplink packet is regenerated."
)
LIVE_CAPABILITY_CONTRACT_OVERRIDES: dict[str, dict[str, object]] = {
    "chat": {
        "default_model": QWEN36_ROUTER_MODEL,
        "default_profile": "qwen36_35_local",
        "status": "routable_live_policy",
        "production_state": "production",
        "benchmark_confidence": "refresh_required",
        "selection_method": "live_model_reality_policy",
        "guardrail": "Use Qwen-first local routing; keep irreversible work behind verifier receipts and explicit policy gates.",
        "alternates_prepend": [
            {
                "model": QWEN36_CODE_MODEL,
                "profile": "qwen36_27_local",
                "role": "coding_operator",
            },
            {
                "model": QWEN35_JUDGE_MODEL,
                "profile": "qwen35_122_local",
                "role": "heavyweight_judge",
            },
        ],
        "notes_append": [
            "Live override: Qwen 3.6 35B is the default interactive router/planner/filter lane.",
            "Gemma lanes remain visible as lab or fallback comparisons, not production defaults.",
        ],
    },
    "vision_grounding": {
        "default_model": QWEN3_VL_MODEL,
        "default_profile": "qwen3vl30_local",
        "status": "partial_live_policy",
        "production_state": "partial",
        "benchmark_confidence": "requires_dedicated_grounding_benchmark",
        "selection_method": "live_model_reality_policy",
        "guardrail": "Use as visual triage only until GroundNext or an equivalent coordinate-grounding service passes live smoke tests.",
        "alternates_prepend": [
            {
                "model": QWEN36_ROUTER_MODEL,
                "profile": "qwen36_35_local",
                "role": "screen_reasoning",
            },
        ],
        "notes_append": [
            "Qwen-VL is installed and routable for local visual reasoning, but dedicated GUI grounding is still a specialist gap.",
        ],
    },
    "doc_parse": {
        "default_model": "paddleocr:PP-OCRv6-small",
        "default_profile": "spark_ocr_small_local",
        "status": "live_tool_lane",
        "production_state": "production",
        "benchmark_confidence": "live_smoke_required",
        "selection_method": "live_tool_lane_policy",
        "dispatch": "ocr_proxy",
        "guardrail": "Use for document triage; require exact table, identifier, and OCR verification before downstream writes.",
        "alternates_prepend": [
            {
                "model": QWEN3_VL_MODEL,
                "profile": "qwen3vl30_local",
                "role": "visual_reasoning_fallback",
            },
        ],
        "notes_append": [
            "PaddleOCR PP-OCRv6 is exposed through /v1/ocr as a production local OCR lane.",
            "MinerU/MonkeyOCR-style document structure services remain pending specialist lanes.",
        ],
    },
    "embed": {
        "default_model": DEFAULT_EMBEDDING_MODEL,
        "default_profile": "bge_m3_local",
        "status": "benchmark_backed_routable",
        "production_state": "production",
        "selection_method": "live_tool_lane_probe",
        "notes_append": [
            "BGE-M3 is the production text embedding lane and is expected to stay warm on Spark capacity.",
        ],
    },
    "rerank": {
        "default_model": DEFAULT_RERANK_MODEL,
        "default_profile": "bge_reranker_m3_cross_encoder_local",
        "status": "live_tool_lane",
        "production_state": "production",
        "selection_method": "live_tool_lane_probe",
        "dispatch": "rerank_proxy",
        "alternates_prepend": [
            {
                "model": DEFAULT_EMBEDDING_MODEL,
                "profile": "bge_m3_cosine_local",
                "role": "embedding_cosine_fallback",
            },
        ],
        "notes_append": [
            "The live rerank endpoint uses the native BGE cross-encoder service by default.",
            "BGE-M3 embedding cosine remains an explicit degraded fallback, not the production scorer.",
        ],
        "notes_suppress_contains": [
            "Rerank score method: `embedding_cosine`.",
        ],
    },
    "hybrid_retrieve": {
        "default_model": DEFAULT_EMBEDDING_MODEL,
        "default_profile": "bge_m3_local",
        "status": "benchmark_backed_routable",
        "production_state": "production",
        "selection_method": "live_tool_lane_probe",
        "notes_append": [
            "Hybrid retrieval should use BGE embeddings plus local rerank before any expensive planner or cloud escalation.",
        ],
    },
    "safety_privacy_classify": {
        "default_model": QWEN3GUARD_MODEL,
        "default_profile": "qwen3guard_stream_06_local",
        "status": "live_tool_lane",
        "production_state": "production",
        "benchmark_confidence": "live_smoke_passed_refresh_required",
        "selection_method": "live_tool_lane_policy",
        "dispatch": "safety_proxy",
        "guardrail": "Use Qwen3Guard for local prompt safety and injection triage; high-authority actions still require verifier and operator gates.",
        "notes_append": [
            "Qwen3Guard Stream 0.6B is exposed through /v1/safety/classify as a production local safety lane.",
            "Prompt-injection-sentinel remains aspirational until its gated artifact is available and smoke-tested.",
        ],
    },
    "entity_event_extract": {
        "default_model": QWEN36_ROUTER_MODEL,
        "default_profile": "qwen36_35_local",
        "status": "routable_live_policy",
        "production_state": "production",
        "benchmark_confidence": "refresh_required",
        "selection_method": "live_model_reality_policy",
    },
    "ops_anomaly": {
        "default_model": QWEN36_ROUTER_MODEL,
        "default_profile": "qwen36_35_local",
        "status": "routable_live_policy",
        "production_state": "production",
        "benchmark_confidence": "refresh_required",
        "selection_method": "live_model_reality_policy",
        "notes_append": [
            "Toto/Chronos forecasting remains a lab lane until live telemetry benchmarks and serving paths exist.",
        ],
    },
    "code_risk": {
        "default_model": QWEN36_CODE_MODEL,
        "default_profile": "qwen36_27_local",
        "status": "routable_live_policy",
        "production_state": "production",
        "benchmark_confidence": "refresh_required",
        "selection_method": "live_model_reality_policy",
        "alternates_prepend": [
            {
                "model": QWEN35_JUDGE_MODEL,
                "profile": "qwen35_122_local",
                "role": "heavyweight_judge",
            },
            {
                "model": QWEN36_ROUTER_MODEL,
                "profile": "qwen36_35_local",
                "role": "fast_reviewer",
            },
        ],
        "notes_append": [
            "Qwen 3.6 27B is the production local coding/risk lane; deterministic experts should still run for real patches.",
        ],
    },
}
HIGH_PAYBACK_MODEL_LANES: list[dict[str, object]] = [
    {
        "lane": "interactive_router_planner_filter",
        "state": "production",
        "models": [QWEN36_ROUTER_MODEL],
        "serving_path": "/v1/chat/completions",
        "notes": "Default local brain for TUI planning, filtering, summaries, and routine verification.",
    },
    {
        "lane": "coding_operator",
        "state": "production",
        "models": [QWEN36_CODE_MODEL],
        "serving_path": "/v1/chat/completions",
        "notes": "Local code/risk lane; use deterministic tools for hard validation.",
    },
    {
        "lane": "heavyweight_judge",
        "state": "production_available",
        "models": [QWEN35_JUDGE_MODEL],
        "serving_path": "/v1/chat/completions",
        "notes": "Local high-cost judge for difficult verification and escalation avoidance.",
    },
    {
        "lane": "text_memory_retrieval",
        "state": "production",
        "models": [DEFAULT_EMBEDDING_MODEL],
        "serving_path": "/v1/embeddings",
        "notes": "BGE-M3 embedding lane is live and benchmark-backed.",
    },
    {
        "lane": "text_rerank",
        "state": "production",
        "models": [BGE_RERANKER_MODEL, DEFAULT_EMBEDDING_MODEL],
        "serving_path": "/v1/rerank",
        "notes": "Native BGE cross-encoder reranking is live on the Spark rerank service; BGE-M3 embedding cosine is the degraded fallback.",
    },
    {
        "lane": "vision_and_document_triage",
        "state": "production_partial",
        "models": ["paddleocr:PP-OCRv6-small", QWEN3_VL_MODEL],
        "serving_path": "/v1/ocr, /v1/chat/completions",
        "notes": "PaddleOCR is production for image/video OCR; Qwen-VL is installed for visual reasoning. Dedicated structured PDF/GUI grounding remains partial.",
    },
    {
        "lane": "asr_media",
        "state": "production",
        "models": ["faster-whisper:distil-large-v3"],
        "serving_path": "/v1/audio/transcriptions",
        "notes": "ASR is served through the media/transcribe lane rather than a chat model.",
    },
    {
        "lane": "safety_prompt_injection",
        "state": "production",
        "models": [QWEN3GUARD_MODEL],
        "serving_path": "/v1/safety/classify",
        "notes": "Qwen3Guard Stream 0.6B is live on the Spark safety service for local prompt safety and injection triage.",
    },
    {
        "lane": "gui_grounding_doc_ocr_safety_forecasting_graph_network",
        "state": "aspirational_or_lab",
        "models": [
            "GroundNext/ShowUI",
            "PaddleOCR/MinerU/MonkeyOCR/dots.mocr",
            "prompt-injection-sentinel",
            "Toto/Chronos",
            "SAM/Depth/LightGlue",
            "GraphPFN/PacketCLIP/DNS-GT/Lens",
        ],
        "serving_path": "",
        "notes": "High-payback, but not default-routable until live smoke tests, schemas, benchmarks, and receipts exist.",
    },
]
HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def unique_items(values: list[str]) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for value in values:
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        rows.append(item)
    return rows


def split_env_urls(name: str, default_rows: tuple[str, ...]) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return list(default_rows)
    return unique_items(raw.split(","))


def split_env_paths(name: str, default_rows: tuple[str, ...]) -> list[Path]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return [Path(item) for item in default_rows if str(item).strip()]
    return [Path(item.strip()) for item in raw.split(",") if item.strip()]


def normalize_base_url(value: str) -> str:
    return value.strip().rstrip("/")


def parse_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except Exception:
        return values
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def read_first_json_doc(paths: list[Path]) -> tuple[dict[str, object] | None, str]:
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload, str(path)
    return None, ""


def frontdoor_for_url(value: str, *, default_port: int) -> str:
    raw = value.strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw if "://" in raw else f"http://{raw}")
    host = (parsed.hostname or "").strip()
    if not host:
        return ""
    scheme = parsed.scheme or "http"
    port = parsed.port or default_port
    if (
        port == 11434
        or port == 8002
        or port == 8100
        or port == 8097
        or port == 8098
        or port == 8102
    ):
        port = default_port
    return normalize_base_url(f"{scheme}://{host}:{port}")


def frontdoors_from_env_values(
    values: dict[str, str], *, default_port: int
) -> list[str]:
    rows: list[str] = []
    for key in ("NORMAN_NORLLAMA_FRONTDOORS", "NORMAN_LOCAL_LLM_FRONTDOORS"):
        raw = values.get(key, "")
        if raw:
            rows.extend(
                normalize_base_url(item)
                for item in raw.split(",")
                if normalize_base_url(item)
            )
    for key in (
        "NORMAN_NORLLAMA_BASE_URL",
        "NORLLAMA_BASE_URL_OVERRIDE",
        "NORMAN_LOCAL_LLM_ENDPOINTS",
    ):
        raw = values.get(key, "")
        if raw:
            rows.extend(
                frontdoor_for_url(item, default_port=default_port)
                for item in raw.split(",")
                if frontdoor_for_url(item, default_port=default_port)
            )
    raw_mapping = values.get("NORMAN_LOCAL_LLM_MODEL_ENDPOINTS", "")
    if raw_mapping:
        try:
            payload = json.loads(raw_mapping)
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            for endpoints in payload.values():
                if not isinstance(endpoints, list):
                    continue
                for item in endpoints:
                    frontdoor = frontdoor_for_url(
                        str(item or ""), default_port=default_port
                    )
                    if frontdoor:
                        rows.append(frontdoor)
    return unique_items(rows)


def gateway_identity() -> dict[str, str]:
    return {
        "name": "norllama",
        "version": GATEWAY_VERSION,
        "build": GATEWAY_BUILD,
        "version_endpoint": "norllama",
    }


def gateway_version_doc() -> dict[str, str]:
    return {
        "version": GATEWAY_VERSION,
        "service": "norllama",
        "name": "norllama",
        "build": GATEWAY_BUILD,
    }


def load_key(
    base_url: str,
    direct_env: str,
    file_env: str,
    default_key_file: str,
    key_dir_env: str,
    default_key_dir: str,
) -> str:
    direct = os.getenv(direct_env, "").strip()
    if direct:
        return direct
    explicit = os.getenv(file_env, "").strip()
    key_dir = Path(os.getenv(key_dir_env, default_key_dir))
    host = (urllib.parse.urlparse(base_url).hostname or "").strip()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if host:
        candidates.append(key_dir / f"{host}.key")
    candidates.append(Path(default_key_file))
    for path in candidates:
        try:
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
    return ""


def guess_content_type(
    filename: str, fallback: str = "application/octet-stream"
) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or fallback


def split_header_params(value: str) -> tuple[str, dict[str, str]]:
    parts = [part.strip() for part in value.split(";") if part.strip()]
    if not parts:
        return "", {}
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, raw_value = part.split("=", 1)
        params[key.strip().lower()] = raw_value.strip().strip('"')
    return parts[0].strip().lower(), params


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def unique_preserve(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def merge_preferred_model_rows(
    preferred: list[dict[str, object]], existing: object
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if isinstance(existing, list):
        rows.extend(row for row in existing if isinstance(row, dict))
    merged: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in [*preferred, *rows]:
        model = str(row.get("model") or row.get("name") or "").strip()
        profile = str(row.get("profile") or "").strip()
        key = f"{model.lower()}|{profile.lower()}"
        if not model or key in seen:
            continue
        seen.add(key)
        merged.append(dict(row))
    return merged


def apply_live_policy_contract_override(row: dict[str, object]) -> dict[str, object]:
    contract_id = str(row.get("contract_id") or "").strip().lower().replace("-", "_")
    override = LIVE_CAPABILITY_CONTRACT_OVERRIDES.get(contract_id)
    if not override:
        return dict(row)
    updated = dict(row)
    previous_default_model = str(updated.get("default_model") or "")
    previous_default_profile = str(updated.get("default_profile") or "")
    for key, value in override.items():
        if key in {"notes_append", "alternates_prepend", "notes_suppress_contains"}:
            continue
        updated[key] = value
    notes = [
        str(item) for item in (updated.get("notes") or []) if str(item or "").strip()
    ]
    suppress_needles = [
        str(item)
        for item in (override.get("notes_suppress_contains") or [])
        if str(item or "").strip()
    ]
    if suppress_needles:
        notes = [
            note
            for note in notes
            if not any(needle in note for needle in suppress_needles)
        ]
    for note in override.get("notes_append") or []:
        text = str(note or "").strip()
        if text and text not in notes:
            notes.append(text)
    if notes:
        updated["notes"] = notes
    preferred = [
        row
        for row in (override.get("alternates_prepend") or [])
        if isinstance(row, dict)
    ]
    if preferred:
        updated["alternates"] = merge_preferred_model_rows(
            preferred, updated.get("alternates")
        )
    allowed_models = {
        str(updated.get("default_model") or "").strip().lower(),
        *[
            str(item.get("model") or item.get("name") or "").strip().lower()
            for item in preferred
            if str(item.get("model") or item.get("name") or "").strip()
        ],
    }
    allowed_models = {item for item in allowed_models if item}
    suppressed_models: list[str] = []
    if allowed_models:
        for key in ("alternates", "suite_hits"):
            filtered: list[dict[str, object]] = []
            for item in updated.get(key) or []:
                if not isinstance(item, dict):
                    continue
                model = str(item.get("model") or item.get("name") or "").strip()
                if model.lower() in allowed_models:
                    filtered.append(item)
                    continue
                if model and model not in suppressed_models:
                    suppressed_models.append(model)
            updated[key] = filtered
    updated["live_policy_override"] = {
        "active": True,
        "reason": LIVE_POLICY_OVERRIDE_REASON,
        "previous_default_model": previous_default_model,
        "previous_default_profile": previous_default_profile,
        "default_model": str(updated.get("default_model") or ""),
        "default_profile": str(updated.get("default_profile") or ""),
        "suppressed_stale_candidate_models": suppressed_models,
    }
    return updated


def should_disable_qwen_thinking(model_id: str) -> bool:
    lower = str(model_id or "").strip().lower()
    return "qwen3.6:" in lower or "qwen3.5:" in lower


def normalize_chat_payload_for_local_qwen(
    payload: dict[str, object],
) -> tuple[dict[str, object], bool]:
    model = str(payload.get("model") or "").strip()
    if not should_disable_qwen_thinking(model) or "think" in payload:
        return payload, False
    normalized = dict(payload)
    normalized["think"] = False
    return normalized, True


def openai_chat_payload_to_ollama(payload: dict[str, object]) -> dict[str, object]:
    model = str(payload.get("model") or "").strip()
    native: dict[str, object] = {
        "model": model,
        "messages": payload.get("messages") or [],
        "stream": False,
        "think": False,
    }
    if payload.get("keep_alive") is not None:
        native["keep_alive"] = payload.get("keep_alive")
    options: dict[str, object] = {}
    existing_options = payload.get("options")
    if isinstance(existing_options, dict):
        options.update(existing_options)
    key_map = {
        "temperature": "temperature",
        "top_p": "top_p",
        "top_k": "top_k",
        "min_p": "min_p",
        "seed": "seed",
        "stop": "stop",
        "max_tokens": "num_predict",
        "max_completion_tokens": "num_predict",
    }
    for source, target in key_map.items():
        if payload.get(source) is not None:
            options[target] = payload.get(source)
    if options:
        native["options"] = options
    return native


def ollama_chat_payload_to_openai(
    payload: dict[str, object], *, model: str
) -> dict[str, object]:
    message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    content = str(message.get("content") or payload.get("response") or "")
    prompt_tokens = int(payload.get("prompt_eval_count") or 0)
    completion_tokens = int(payload.get("eval_count") or 0)
    done_reason = str(payload.get("done_reason") or "").strip() or (
        "stop" if payload.get("done") else None
    )
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "system_fingerprint": "fp_norllama_native_ollama",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": done_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "norllama": {
            "capability": "chat",
            "bridge": "native_ollama_chat",
            "think": False,
            "output_shape": "complete" if content else "empty",
        },
    }


def infer_model_capabilities(model_id: str, provider: str) -> list[str]:
    lower = model_id.lower()
    caps: list[str] = []
    if provider == "ds4":
        caps.extend(["chat", "reasoning"])
    elif provider == "safety" or "guard" in lower:
        caps.extend(["safety", "prompt_injection"])
    elif "whisper" in lower or "asr" in lower:
        caps.extend(["audio", "transcribe"])
    elif "rerank" in lower or "reranker" in lower:
        caps.append("rerank")
    elif "stable-diffusion" in lower or "sdxl" in lower or "txt2img" in lower:
        caps.append("image_generate")
    elif (
        "embed" in lower
        or lower.startswith("nomic-embed")
        or lower in {"bge-m3:latest"}
    ):
        caps.append("embed")
    else:
        caps.append("chat")
    if "vl:" in lower or "-vl" in lower or "vision" in lower:
        caps.append("vision")
    if "coder" in lower or "devstral" in lower:
        caps.append("code")
    return unique_preserve(caps)


def infer_model_access(model_id: str, provider: str, capabilities: list[str]) -> str:
    if provider == "ds4":
        return "unified_chat"
    if "safety" in capabilities:
        return "safety_proxy"
    if (
        "embed" in capabilities
        or "rerank" in capabilities
        or "transcribe" in capabilities
        or "image_generate" in capabilities
    ):
        return "passthrough_only"
    if "vision" in capabilities:
        return "unified_chat_text_only"
    return "unified_chat"


def infer_model_summary(model_id: str, provider: str, capabilities: list[str]) -> str:
    lower = model_id.lower()
    if provider == "ds4" and "flash" in lower:
        return "Fast DS4 DeepSeek lane for unified chat and runtime testing."
    if provider == "ds4" and "pro" in lower:
        return (
            "Heavier DS4 DeepSeek lane exposed through the same unified chat surface."
        )
    if "openfugu" in lower:
        return "Compact lab chat model; do not use as a production default unless a lane-specific benchmark beats Qwen."
    if lower.startswith("gemma4:26b"):
        return "Legacy benchmark winner kept for comparison and fallback; Qwen-first policy is now preferred."
    if lower.startswith("gemma4:31b"):
        return "Legacy larger Gemma lane kept for fallback and benchmark comparison."
    if "qwen3.6:35b" in lower:
        return "Production local router/planner/filter lane for the Spark fleet."
    if "qwen3.6:27b" in lower or "qwen3.5:27b" in lower:
        return "Production local coding/operator lane for repo and implementation work."
    if "qwen3.5:122b" in lower:
        return "Heavyweight local judge lane for difficult verification and escalation avoidance."
    if "qwen3-coder-next" in lower or "qwen3-coder:" in lower:
        return "Code-focused Qwen lane for repo and implementation work."
    if "qwen3-vl" in lower:
        return "Vision-capable Qwen lane; local visual reasoning is live, dedicated grounding/OCR is still partial."
    if "gpt-oss:120b" in lower:
        return "Large local reasoning-style lane; expensive but capable."
    if "nemotron-3-super:120b" in lower:
        return "Large experimental local lane; useful for heavyweight comparisons."
    if "llama4:scout" in lower:
        return "Lighter Llama 4 lane for practical general chat."
    if "llama4:maverick" in lower:
        return "Larger Llama 4 sibling to Scout."
    if "devstral" in lower:
        return "Smaller dev/code-oriented local lane."
    if "embed" in capabilities:
        return (
            "Production embedding lane for memory, retrieval, and evidence filtering."
        )
    if "rerank" in capabilities:
        return "Production reranker lane for local evidence ordering before expensive planner or cloud calls."
    if "safety" in capabilities:
        return "Production local safety and prompt-injection classification lane."
    if "transcribe" in capabilities:
        return "Audio/transcription lane served through media/transcribe, not unified chat."
    if "image_generate" in capabilities:
        return (
            "Stable Diffusion-compatible image generation lane served through Norllama."
        )
    if "chat" in capabilities:
        return "General local chat lane."
    return "Specialized local model."


def fetch_url(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> tuple[int, dict[str, str], bytes]:
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(url, data=body, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return int(resp.status), dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), dict(exc.headers.items()), exc.read()


def extract_jsonish_final_object(body: bytes) -> dict | None:
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidates = list(reversed(lines)) if lines else [text]
    for chunk in candidates:
        try:
            obj = json.loads(chunk)
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    try:
        obj = json.loads(text)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def extract_ollama_metrics(body: bytes, content_type: str) -> dict[str, object]:
    lower = (content_type or "").lower()
    if "json" not in lower and "ndjson" not in lower:
        return {}
    final_obj = extract_jsonish_final_object(body)
    if not isinstance(final_obj, dict):
        return {}
    metrics: dict[str, object] = {}
    model = str(final_obj.get("model") or "").strip()
    if model:
        metrics["model"] = model
    for key in (
        "load_duration",
        "total_duration",
        "prompt_eval_duration",
        "eval_duration",
        "prompt_eval_count",
        "eval_count",
    ):
        value = final_obj.get(key)
        if value is None:
            continue
        try:
            metrics[key] = int(value)
        except Exception:
            continue
    if "load_duration" in metrics:
        metrics["load_duration_ms"] = round(
            int(metrics["load_duration"]) / 1_000_000, 3
        )
    if "total_duration" in metrics:
        metrics["total_duration_ms"] = round(
            int(metrics["total_duration"]) / 1_000_000, 3
        )
    return metrics


class App:
    def __init__(self) -> None:
        self.bind = os.getenv("NORLLAMA_BIND", DEFAULT_BIND).strip() or DEFAULT_BIND
        self.port = int(os.getenv("NORLLAMA_PORT", str(DEFAULT_PORT)))
        self.timeout_s = float(os.getenv("NORLLAMA_TIMEOUT_S", str(DEFAULT_TIMEOUT_S)))
        self.model_cache_ttl_s = float(
            os.getenv("NORLLAMA_MODEL_CACHE_TTL_S", str(DEFAULT_MODEL_CACHE_TTL_S))
        )
        self.inventory_timeout_s = float(
            os.getenv("NORLLAMA_INVENTORY_TIMEOUT_S", str(DEFAULT_INVENTORY_TIMEOUT_S))
        )
        self.activity_limit = int(
            os.getenv("NORLLAMA_ACTIVITY_LIMIT", str(DEFAULT_ACTIVITY_LIMIT))
        )
        self.tool_activity_limit = int(
            os.getenv("NORLLAMA_TOOL_ACTIVITY_LIMIT", str(DEFAULT_TOOL_ACTIVITY_LIMIT))
        )
        self.prefetch_job_ttl_s = float(
            os.getenv("NORLLAMA_PREFETCH_JOB_TTL_S", str(DEFAULT_PREFETCH_JOB_TTL_S))
        )
        self.prefetch_job_limit = int(
            os.getenv("NORLLAMA_PREFETCH_JOB_LIMIT", str(DEFAULT_PREFETCH_JOB_LIMIT))
        )
        self.expose_upstream_details = env_flag(
            "NORLLAMA_EXPOSE_UPSTREAM_DETAILS", False
        )
        self.advertise_aux_services = env_flag("NORLLAMA_ADVERTISE_AUX_SERVICES", False)
        self.public_provider_name = (
            os.getenv("NORLLAMA_PUBLIC_PROVIDER_NAME", "norllama").strip() or "norllama"
        )
        self.ollama_bases = split_env_urls(
            "NORLLAMA_OLLAMA_BASES", DEFAULT_OLLAMA_BASES
        )
        self.peer_timeout_s = float(
            os.getenv("NORLLAMA_PEER_TIMEOUT_S", str(DEFAULT_PEER_TIMEOUT_S))
        )
        self.max_peer_hops = max(
            0, int(os.getenv("NORLLAMA_MAX_PEER_HOPS", str(DEFAULT_MAX_PEER_HOPS)))
        )
        self.discovery_env_files = split_env_urls(
            "NORLLAMA_DISCOVERY_ENV_FILES", DEFAULT_DISCOVERY_ENV_FILES
        )
        self.benchmark_packet_paths = split_env_paths(
            "NORLLAMA_BENCHMARK_PACKET_PATHS",
            DEFAULT_BENCHMARK_PACKET_PATHS,
        )
        self.preflight_packet_paths = split_env_paths(
            "NORLLAMA_PREFLIGHT_PACKET_PATHS",
            DEFAULT_PREFLIGHT_PACKET_PATHS,
        )
        self.self_base_urls = unique_items(
            [
                normalize_base_url(os.getenv("NORLLAMA_SELF_BASE", "")),
                normalize_base_url(f"http://{self.bind}:{self.port}"),
                normalize_base_url(f"http://127.0.0.1:{self.port}"),
                normalize_base_url(f"http://localhost:{self.port}"),
            ]
        )
        legacy_ds4_base = os.getenv("NORLLAMA_DS4_BASE", "").strip()
        self.ds4_bases = split_env_urls(
            "NORLLAMA_DS4_BASES",
            (legacy_ds4_base,) if legacy_ds4_base else DEFAULT_DS4_BASES,
        )
        self.ds4_base = self.ds4_bases[0] if self.ds4_bases else DEFAULT_DS4_BASE
        self.media_bases = split_env_urls("NORLLAMA_MEDIA_BASES", DEFAULT_MEDIA_BASES)
        self.transcribe_bases = split_env_urls(
            "NORLLAMA_TRANSCRIBE_BASES", DEFAULT_TRANSCRIBE_BASES
        )
        self.ocr_bases = split_env_urls("NORLLAMA_OCR_BASES", DEFAULT_OCR_BASES)
        self.rerank_bases = split_env_urls(
            "NORLLAMA_RERANK_BASES", DEFAULT_RERANK_BASES
        )
        self.safety_bases = split_env_urls(
            "NORLLAMA_SAFETY_BASES", DEFAULT_SAFETY_BASES
        )
        image_bases = split_env_urls("NORLLAMA_IMAGE_BASES", DEFAULT_IMAGE_BASES)
        sd_bases = split_env_urls("NORLLAMA_STABLE_DIFFUSION_BASES", ())
        self.image_bases = unique_items([*image_bases, *sd_bases])
        auto_peer_candidates: list[str] = []
        for env_path in self.discovery_env_files:
            auto_peer_candidates.extend(
                frontdoors_from_env_values(
                    parse_env_file(env_path), default_port=self.port
                )
            )
        for value in [
            *self.ollama_bases,
            *self.ds4_bases,
            *self.media_bases,
            *self.transcribe_bases,
            *self.ocr_bases,
            *self.rerank_bases,
            *self.safety_bases,
            *self.image_bases,
        ]:
            frontdoor = frontdoor_for_url(value, default_port=self.port)
            if frontdoor:
                auto_peer_candidates.append(frontdoor)
        explicit_peer_bases = split_env_urls("NORLLAMA_PEER_BASES", DEFAULT_PEER_BASES)
        self.peer_bases = [
            base
            for base in (explicit_peer_bases or unique_items(auto_peer_candidates))
            if normalize_base_url(base)
            and normalize_base_url(base) not in self.self_base_urls
        ]
        self._lock = threading.Lock()
        self._ollama_inventory_cache: tuple[float, list[dict]] | None = None
        self._ollama_inventory_refreshing = False
        self._ds4_inventory_cache: tuple[float, list[dict]] | None = None
        self._recent_activity: list[dict[str, object]] = []
        self._recent_tool_activity: list[dict[str, object]] = []
        self._prefetch_jobs: dict[str, dict[str, object]] = {}
        self._prefetch_job_keys: dict[str, str] = {}

    def public_provider(self, provider: str) -> str:
        return provider if self.expose_upstream_details else self.public_provider_name

    def public_summary(
        self, provider: str, capabilities: list[str], summary: str
    ) -> str:
        if self.expose_upstream_details:
            return summary
        if provider == "ds4":
            return "Unified chat lane available through Norllama."
        if "transcribe" in capabilities:
            return "Transcription lane available through Norllama."
        if "embed" in capabilities:
            return "Embedding lane available through Norllama."
        if "rerank" in capabilities:
            return "Reranker lane available through Norllama."
        if "safety" in capabilities:
            return "Safety classification lane available through Norllama."
        if "ocr" in capabilities:
            return "OCR/document parsing lane available through Norllama."
        if "image_generate" in capabilities:
            return "Image generation lane available through Norllama."
        return summary.replace("Spark fleet", "Norllama fleet").replace(
            "Spark", "Norllama"
        )

    def public_endpoints(self) -> list[dict[str, object]]:
        endpoints: list[dict[str, object]] = [
            {"path": "/", "methods": ["GET", "HEAD", "OPTIONS"], "kind": "human_ui"},
            {"path": "/ui", "methods": ["GET", "HEAD", "OPTIONS"], "kind": "human_ui"},
            {
                "path": "/health",
                "methods": ["GET", "HEAD", "OPTIONS"],
                "kind": "status",
            },
            {
                "path": "/healthz",
                "methods": ["GET", "HEAD", "OPTIONS"],
                "kind": "status",
            },
            {
                "path": "/v1/models",
                "methods": ["GET", "HEAD", "OPTIONS"],
                "kind": "inventory",
            },
            {
                "path": "/v1/overview",
                "methods": ["GET", "HEAD", "OPTIONS"],
                "kind": "overview",
            },
            {
                "path": "/v1/catalog",
                "methods": ["GET", "HEAD", "OPTIONS"],
                "kind": "inventory",
            },
            {
                "path": "/v1/capabilities",
                "methods": ["GET", "HEAD", "OPTIONS"],
                "kind": "contract",
            },
            {
                "path": "/v1/capabilities/{contract}",
                "methods": ["GET", "HEAD", "POST", "OPTIONS"],
                "kind": "contract",
            },
            {
                "path": "/v1/warm-policy",
                "methods": ["GET", "HEAD", "OPTIONS"],
                "kind": "load_management",
            },
            {
                "path": "/v1/activity",
                "methods": ["GET", "HEAD", "OPTIONS"],
                "kind": "observability",
            },
            {
                "path": "/v1/prefetch",
                "methods": ["POST", "OPTIONS"],
                "kind": "load_management",
            },
            {
                "path": "/v1/prefetch/status",
                "methods": ["GET", "HEAD", "OPTIONS"],
                "kind": "load_management",
            },
            {
                "path": "/v1/evict",
                "methods": ["POST", "OPTIONS"],
                "kind": "load_management",
            },
            {
                "path": "/api/version",
                "methods": ["GET", "HEAD", "OPTIONS"],
                "kind": "gateway_status",
            },
            {
                "path": "/api/tags",
                "methods": ["GET", "HEAD", "OPTIONS"],
                "kind": "ollama_compat",
            },
            {
                "path": "/api/ps",
                "methods": ["GET", "HEAD", "OPTIONS"],
                "kind": "ollama_compat",
            },
            {
                "path": "/api/chat",
                "methods": ["POST", "OPTIONS"],
                "kind": "ollama_compat",
            },
            {
                "path": "/api/generate",
                "methods": ["POST", "OPTIONS"],
                "kind": "ollama_compat",
            },
            {
                "path": "/api/show",
                "methods": ["POST", "OPTIONS"],
                "kind": "ollama_compat",
            },
            {
                "path": "/api/embed",
                "methods": ["POST", "OPTIONS"],
                "kind": "ollama_compat",
            },
            {
                "path": "/api/embeddings",
                "methods": ["POST", "OPTIONS"],
                "kind": "embedding",
            },
            {
                "path": "/v1/embeddings",
                "methods": ["POST", "OPTIONS"],
                "kind": "embedding",
            },
            {"path": "/v1/rerank", "methods": ["POST", "OPTIONS"], "kind": "rerank"},
            {"path": "/rerank", "methods": ["POST", "OPTIONS"], "kind": "rerank"},
            {
                "path": "/v1/safety/classify",
                "methods": ["POST", "OPTIONS"],
                "kind": "safety",
            },
            {
                "path": "/safety/classify",
                "methods": ["POST", "OPTIONS"],
                "kind": "safety",
            },
            {"path": "/v1/ocr", "methods": ["POST", "OPTIONS"], "kind": "ocr"},
            {"path": "/ocr", "methods": ["POST", "OPTIONS"], "kind": "ocr"},
            {
                "path": "/v1/images/generations",
                "methods": ["POST", "OPTIONS"],
                "kind": "image_generate",
            },
            {
                "path": "/v1/chat/completions",
                "methods": ["POST", "OPTIONS"],
                "kind": "unified_chat",
            },
        ]
        if self.advertise_aux_services:
            endpoints.extend(
                [
                    {
                        "path": "/transcribe",
                        "methods": ["POST", "OPTIONS"],
                        "kind": "asr",
                    },
                    {
                        "path": "/v1/audio/transcriptions",
                        "methods": ["POST", "OPTIONS"],
                        "kind": "asr",
                    },
                    {
                        "path": "/media/*",
                        "methods": ["POST", "OPTIONS"],
                        "kind": "media",
                    },
                ]
            )
        if self.expose_upstream_details:
            endpoints.extend(
                [
                    {
                        "path": "/ollama/*",
                        "methods": ["GET", "HEAD", "POST", "OPTIONS"],
                        "kind": "passthrough",
                    },
                    {
                        "path": "/ds4/*",
                        "methods": ["GET", "HEAD", "POST", "OPTIONS"],
                        "kind": "passthrough",
                    },
                ]
            )
        return endpoints

    def public_candidate_rows(
        self, lane: str, rows: list[dict] | None
    ) -> dict[str, object] | list[dict]:
        if self.expose_upstream_details:
            return rows or []
        all_rows = rows or []
        healthy = 0
        for row in all_rows:
            if row.get("healthy") or str(row.get("status") or "").lower() == "ok":
                healthy += 1
        return {
            "lane": lane,
            "candidate_count": len(all_rows),
            "healthy_count": healthy,
        }

    def public_activity_item(self, item: dict[str, object]) -> dict[str, object]:
        row = dict(item)
        if not self.expose_upstream_details:
            for key in ("upstream", "attempts", "prefetch_upstream", "evict_hosts"):
                row.pop(key, None)
        return row

    def media_key(self, base_url: str) -> str:
        return load_key(
            base_url,
            "NORLLAMA_MEDIA_API_KEY",
            "NORLLAMA_MEDIA_API_KEY_FILE",
            DEFAULT_MEDIA_KEY_FILE,
            "NORLLAMA_MEDIA_KEY_DIR",
            DEFAULT_MEDIA_KEY_DIR,
        )

    def transcribe_key(self, base_url: str) -> str:
        return load_key(
            base_url,
            "NORLLAMA_TRANSCRIBE_API_KEY",
            "NORLLAMA_TRANSCRIBE_API_KEY_FILE",
            DEFAULT_TRANSCRIBE_KEY_FILE,
            "NORLLAMA_TRANSCRIBE_KEY_DIR",
            DEFAULT_TRANSCRIBE_KEY_DIR,
        )

    def ocr_key(self, base_url: str) -> str:
        return load_key(
            base_url,
            "NORLLAMA_OCR_API_KEY",
            "NORLLAMA_OCR_API_KEY_FILE",
            DEFAULT_OCR_KEY_FILE,
            "NORLLAMA_OCR_KEY_DIR",
            DEFAULT_OCR_KEY_DIR,
        )

    def rerank_key(self, base_url: str) -> str:
        return load_key(
            base_url,
            "NORLLAMA_RERANK_API_KEY",
            "NORLLAMA_RERANK_API_KEY_FILE",
            DEFAULT_RERANK_KEY_FILE,
            "NORLLAMA_RERANK_KEY_DIR",
            DEFAULT_RERANK_KEY_DIR,
        )

    def safety_key(self, base_url: str) -> str:
        return load_key(
            base_url,
            "NORLLAMA_SAFETY_API_KEY",
            "NORLLAMA_SAFETY_API_KEY_FILE",
            DEFAULT_SAFETY_KEY_FILE,
            "NORLLAMA_SAFETY_KEY_DIR",
            DEFAULT_SAFETY_KEY_DIR,
        )

    def image_key(self, base_url: str) -> str:
        return load_key(
            base_url,
            "NORLLAMA_IMAGE_API_KEY",
            "NORLLAMA_IMAGE_API_KEY_FILE",
            DEFAULT_IMAGE_KEY_FILE,
            "NORLLAMA_IMAGE_KEY_DIR",
            DEFAULT_IMAGE_KEY_DIR,
        )

    def fetch_json(self, url: str, *, timeout_s: float | None = None) -> dict:
        status, _, body = fetch_url(
            url, timeout_s=self.timeout_s if timeout_s is None else timeout_s
        )
        text = body.decode("utf-8", errors="replace")
        doc = json.loads(text)
        doc["_http_status"] = status
        return doc

    def fetch_json_or_none(
        self, url: str, *, timeout_s: float | None = None
    ) -> dict | None:
        try:
            return self.fetch_json(url, timeout_s=timeout_s)
        except Exception:
            return None

    def choose_healthy(
        self, bases: list[str], suffix: str, *, timeout_s: float | None = None
    ) -> str | None:
        for base in bases:
            try:
                status, _, _ = fetch_url(
                    base.rstrip("/") + suffix,
                    timeout_s=min(self.timeout_s, 10)
                    if timeout_s is None
                    else timeout_s,
                )
                if 200 <= status < 300:
                    return base
            except Exception:
                continue
        return None

    def cached_value(self, cache_name: str, ttl_s: float, builder) -> object:
        now = time.time()
        with self._lock:
            cached = getattr(self, cache_name, None)
            if cached is not None:
                ts, value = cached
                if now - ts < ttl_s:
                    return value
        value = builder()
        with self._lock:
            setattr(self, cache_name, (now, value))
        return value

    def ollama_host_rows(self, *, force: bool = False) -> list[dict]:
        def build() -> list[dict]:
            rows: list[dict] = []
            inventory_timeout_s = min(self.timeout_s, self.inventory_timeout_s)
            for base in self.ollama_bases:
                row: dict[str, object] = {
                    "base_url": base,
                    "healthy": False,
                    "http_status": 0,
                    "loaded_models": None,
                    "model_count": 0,
                    "models": [],
                    "model_docs": [],
                    "tag_docs": [],
                    "ps_docs": [],
                }
                tags_doc = self.fetch_json_or_none(
                    base.rstrip("/") + "/api/tags", timeout_s=inventory_timeout_s
                )
                if tags_doc is not None:
                    row["healthy"] = 200 <= int(tags_doc.get("_http_status") or 0) < 300
                    row["http_status"] = int(tags_doc.get("_http_status") or 0)
                    tag_docs = list(tags_doc.get("models") or [])
                    row["tag_docs"] = tag_docs
                    row["models"] = [
                        str(model.get("model") or model.get("name") or "").strip()
                        for model in tag_docs
                        if str(model.get("model") or model.get("name") or "").strip()
                    ]
                    row["model_docs"] = [
                        {
                            "id": model_id,
                            "object": "model",
                            "created": 0,
                            "owned_by": "ollama",
                            "digest": model.get("digest"),
                            "details": model.get("details"),
                        }
                        for model, model_id in (
                            (
                                model,
                                str(
                                    model.get("model") or model.get("name") or ""
                                ).strip(),
                            )
                            for model in tag_docs
                        )
                        if model_id
                    ]
                    row["model_count"] = len(row["models"])
                if not row.get("models"):
                    v1_doc = self.fetch_json_or_none(
                        base.rstrip("/") + "/v1/models", timeout_s=inventory_timeout_s
                    )
                    if v1_doc is not None:
                        model_docs = list(v1_doc.get("data") or [])
                        row["healthy"] = (
                            200 <= int(v1_doc.get("_http_status") or 0) < 300
                        )
                        row["http_status"] = int(v1_doc.get("_http_status") or 0)
                        if model_docs:
                            row["models"] = [
                                str(model.get("id") or "").strip()
                                for model in model_docs
                                if str(model.get("id") or "").strip()
                            ]
                            row["model_docs"] = model_docs
                            row["model_count"] = len(row["models"])
                if (
                    not row.get("healthy")
                    and not row.get("error")
                    and row.get("http_status") == 0
                ):
                    row["error"] = "inventory_unavailable"
                ps_doc = self.fetch_json_or_none(
                    base.rstrip("/") + "/api/ps", timeout_s=inventory_timeout_s
                )
                if ps_doc is not None:
                    ps_models = list(ps_doc.get("models") or [])
                    row["ps_docs"] = ps_models
                    row["loaded_models"] = len(ps_models)
                rows.append(row)
            return rows

        def background_refresh() -> None:
            try:
                rows = build()
                with self._lock:
                    self._ollama_inventory_cache = (time.time(), rows)
            finally:
                with self._lock:
                    self._ollama_inventory_refreshing = False

        if force:
            rows = build()
            with self._lock:
                self._ollama_inventory_cache = (time.time(), rows)
            return rows

        now = time.time()
        with self._lock:
            cached = self._ollama_inventory_cache
            refreshing = self._ollama_inventory_refreshing
            if cached is not None:
                ts, rows = cached
                if now - ts < self.model_cache_ttl_s:
                    return rows
                if not refreshing:
                    self._ollama_inventory_refreshing = True
                    thread = threading.Thread(
                        target=background_refresh,
                        name="norllama-ollama-refresh",
                        daemon=True,
                    )
                    thread.start()
                return rows

        rows = build()
        with self._lock:
            self._ollama_inventory_cache = (time.time(), rows)
            self._ollama_inventory_refreshing = False
        return rows

    def ds4_host_rows(self, *, force: bool = False) -> list[dict]:
        def build() -> list[dict]:
            rows: list[dict] = []
            inventory_timeout_s = min(self.timeout_s, self.inventory_timeout_s)
            for base in self.ds4_bases:
                row: dict[str, object] = {
                    "base_url": base,
                    "healthy": False,
                    "http_status": 0,
                    "model_count": 0,
                    "models": [],
                    "model_docs": [],
                }
                doc = self.fetch_json_or_none(
                    base.rstrip("/") + "/v1/models", timeout_s=inventory_timeout_s
                )
                if doc is not None:
                    row["healthy"] = 200 <= int(doc.get("_http_status") or 0) < 300
                    row["http_status"] = int(doc.get("_http_status") or 0)
                    model_docs = list(doc.get("data") or [])
                    row["model_docs"] = model_docs
                    row["models"] = [
                        str(model.get("id") or "").strip()
                        for model in model_docs
                        if str(model.get("id") or "").strip()
                    ]
                    row["model_count"] = len(row["models"])
                if not row.get("healthy") and row.get("http_status") == 0:
                    row["error"] = "inventory_unavailable"
                rows.append(row)
            return rows

        if force:
            rows = build()
            with self._lock:
                self._ds4_inventory_cache = (time.time(), rows)
            return rows
        return self.cached_value("_ds4_inventory_cache", self.model_cache_ttl_s, build)  # type: ignore[return-value]

    def ds4_models_doc(self, *, force: bool = False) -> dict:
        merged: dict[str, dict] = {}
        for row in self.ds4_host_rows(force=force):
            base = str(row.get("base_url") or "")
            for model in row.get("model_docs") or []:
                model_id = str(model.get("id") or "").strip()
                if not model_id:
                    continue
                if model_id not in merged:
                    item = dict(model)
                    if self.expose_upstream_details:
                        item["hosts"] = [base]
                    merged[model_id] = item
                elif self.expose_upstream_details and base not in merged[model_id].get(
                    "hosts", []
                ):
                    merged[model_id]["hosts"].append(base)
        return {
            "object": "list",
            "data": sorted(merged.values(), key=lambda item: str(item.get("id") or "")),
        }

    def ds4_model_ids(self) -> set[str]:
        try:
            doc = self.ds4_models_doc()
        except Exception:
            return set()
        return {
            str(model.get("id") or "").strip()
            for model in (doc.get("data") or [])
            if str(model.get("id") or "").strip()
        }

    def choose_ds4_base(
        self, model_id: str | None = None
    ) -> tuple[str | None, list[dict]]:
        rows = self.ds4_host_rows()
        healthy = [row for row in rows if row.get("healthy")]
        if not healthy:
            return None, rows
        if model_id:
            matched = [
                row for row in healthy if model_id in set(row.get("models") or [])
            ]
            if not matched:
                return None, rows
            healthy = matched
        healthy.sort(
            key=lambda row: (
                -int(row.get("model_count") or 0),
                str(row.get("base_url") or ""),
            )
        )
        return str(healthy[0]["base_url"]), rows

    def ds4_candidate_bases(
        self, model_id: str | None = None
    ) -> tuple[list[str], list[dict]]:
        rows = self.ds4_host_rows()
        healthy = [row for row in rows if row.get("healthy")]
        if model_id:
            healthy = [
                row for row in healthy if model_id in set(row.get("models") or [])
            ]
        healthy.sort(
            key=lambda row: (
                -int(row.get("model_count") or 0),
                str(row.get("base_url") or ""),
            )
        )
        return [str(row["base_url"]) for row in healthy], rows

    def peer_frontdoor_rows(self) -> list[dict]:
        rows: list[dict] = []
        timeout_s = min(self.timeout_s, self.peer_timeout_s)
        for base in self.peer_bases:
            row: dict[str, object] = {
                "base_url": base,
                "healthy": False,
                "http_status": 0,
                "service": "",
            }
            doc = self.fetch_json_or_none(
                base.rstrip("/") + "/healthz", timeout_s=timeout_s
            )
            if doc is not None:
                row["http_status"] = int(doc.get("_http_status") or 0)
                row["healthy"] = (
                    200 <= int(doc.get("_http_status") or 0) < 300
                    and str(doc.get("service") or "") == "norllama"
                )
                row["service"] = str(doc.get("service") or "")
            if not row.get("healthy") and row.get("http_status") == 0:
                row["error"] = "peer_unreachable"
            rows.append(row)
        return rows

    def peer_candidate_bases(
        self, model_id: str | None = None
    ) -> tuple[list[str], list[dict]]:
        rows = self.peer_frontdoor_rows()
        healthy = [row for row in rows if row.get("healthy")]
        clean_model = str(model_id or "").strip()
        if clean_model:
            timeout_s = min(self.timeout_s, self.peer_timeout_s)
            for row in healthy:
                base = str(row.get("base_url") or "").strip()
                if not base:
                    continue
                ps_doc = self.fetch_json_or_none(
                    base.rstrip("/") + "/api/ps?scope=local", timeout_s=timeout_s
                )
                ps_rows = list((ps_doc or {}).get("models") or [])
                active_docs = [
                    item
                    for item in ps_rows
                    if isinstance(item, dict)
                    and str(item.get("model") or item.get("name") or "").strip()
                    == clean_model
                ]
                if active_docs:
                    doc = active_docs[0]
                    size = max(1, int(doc.get("size") or 0))
                    size_vram = max(0, int(doc.get("size_vram") or 0))
                    row["model_active"] = True
                    row["model_vram_ratio"] = round(size_vram / size, 6)
                    row["model_size_vram"] = size_vram
                    continue
                tags_doc = self.fetch_json_or_none(
                    base.rstrip("/") + "/api/tags", timeout_s=timeout_s
                )
                tag_rows = list((tags_doc or {}).get("models") or [])
                row["model_available"] = any(
                    isinstance(item, dict)
                    and str(
                        item.get("model") or item.get("name") or item.get("id") or ""
                    ).strip()
                    == clean_model
                    for item in tag_rows
                )
            model_aware = [
                row
                for row in healthy
                if row.get("model_active") or row.get("model_available")
            ]
            if model_aware:
                healthy = model_aware
            healthy.sort(
                key=lambda row: (
                    0 if row.get("model_active") else 1,
                    -float(row.get("model_vram_ratio") or 0.0),
                    -int(row.get("model_size_vram") or 0),
                    str(row.get("base_url") or ""),
                )
            )
        else:
            healthy.sort(key=lambda row: str(row.get("base_url") or ""))
        return [str(row["base_url"]) for row in healthy], rows

    def ollama_candidate_bases(
        self, model_id: str | None = None
    ) -> tuple[list[str], list[dict]]:
        rows = self.ollama_host_rows()
        healthy = [row for row in rows if row.get("healthy")]
        if model_id:
            healthy = [
                row for row in healthy if model_id in set(row.get("models") or [])
            ]
        healthy.sort(
            key=lambda row: (
                int(
                    row.get("loaded_models")
                    if row.get("loaded_models") is not None
                    else 10**9
                ),
                str(row.get("base_url") or ""),
            )
        )
        return [str(row["base_url"]) for row in healthy], rows

    def choose_ollama_base(
        self, model_id: str | None = None
    ) -> tuple[str | None, list[dict]]:
        bases, rows = self.ollama_candidate_bases(model_id)
        if not bases:
            return None, rows
        return bases[0], rows

    def choose_ollama_bases_for_model(
        self, model_id: str
    ) -> tuple[list[str], list[dict]]:
        return self.ollama_candidate_bases(model_id)

    def choose_ollama_version_base(self) -> str | None:
        rows = self.ollama_host_rows()
        healthy = [
            str(row.get("base_url") or "")
            for row in rows
            if row.get("healthy") and str(row.get("base_url") or "")
        ]
        if healthy:
            return healthy[0]
        return self.choose_healthy(
            self.ollama_bases,
            "/api/version",
            timeout_s=min(self.timeout_s, self.inventory_timeout_s),
        )

    def merged_ollama_tags(self) -> dict:
        merged: dict[str, dict] = {}
        for row in self.ollama_host_rows():
            base = str(row.get("base_url") or "")
            for model in row.get("tag_docs") or []:
                model_id = str(model.get("model") or model.get("name") or "").strip()
                if not model_id or model_id in HIDDEN_MODEL_IDS:
                    continue
                if model_id not in merged:
                    item = dict(model)
                    item["model"] = model_id
                    item["name"] = str(item.get("name") or model_id)
                    if self.expose_upstream_details:
                        item["hosts"] = [base]
                    merged[model_id] = item
                elif (
                    self.expose_upstream_details
                    and base not in merged[model_id]["hosts"]
                ):
                    merged[model_id]["hosts"].append(base)
        return {
            "models": sorted(
                merged.values(),
                key=lambda item: str(item.get("name") or item.get("model") or ""),
            )
        }

    def merged_ollama_ps(self, *, include_peers: bool = False) -> dict:
        models: list[dict] = []
        for row in self.ollama_host_rows():
            base = str(row.get("base_url") or "")
            for model in row.get("ps_docs") or []:
                model_id = str(model.get("model") or model.get("name") or "").strip()
                if not model_id or model_id in HIDDEN_MODEL_IDS:
                    continue
                item = dict(model)
                if self.expose_upstream_details:
                    item["host"] = base
                models.append(item)
        if include_peers:
            for base in self.peer_bases:
                doc = self.fetch_json_or_none(
                    base.rstrip("/") + "/api/ps?scope=local",
                    timeout_s=min(self.timeout_s, self.peer_timeout_s),
                )
                if doc is None:
                    continue
                for model in doc.get("models") or []:
                    if not isinstance(model, dict):
                        continue
                    model_id = str(
                        model.get("model") or model.get("name") or ""
                    ).strip()
                    if not model_id or model_id in HIDDEN_MODEL_IDS:
                        continue
                    item = dict(model)
                    if self.expose_upstream_details:
                        item["gateway_host"] = base
                    models.append(item)
        deduped: list[dict] = []
        seen: set[tuple[str, str, str]] = set()
        for item in models:
            model_id = str(item.get("model") or item.get("name") or "").strip().lower()
            key = (
                model_id,
                str(item.get("gateway_host") or ""),
                str(item.get("host") or ""),
            )
            if not model_id or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        deduped.sort(
            key=lambda item: (
                str(item.get("name") or item.get("model") or ""),
                str(item.get("gateway_host") or ""),
                str(item.get("host") or ""),
            )
        )
        return {"models": deduped}

    def choose_media_base(self) -> tuple[str | None, list[dict]]:
        rows: list[dict] = []
        for base in self.media_bases:
            try:
                doc = self.fetch_json(base.rstrip("/") + "/health")
                row = {
                    "base_url": base,
                    "status": doc.get("status"),
                    "busy": bool((doc.get("busy") or {}).get("active")),
                    "free_mib": int(
                        ((doc.get("gpu_memory") or {}).get("free_mib") or 0)
                    ),
                    "http_status": int(doc.get("_http_status") or 0),
                }
                rows.append(row)
            except Exception as exc:
                rows.append({"base_url": base, "status": "error", "error": str(exc)})
        healthy = [row for row in rows if row.get("status") == "ok"]
        if not healthy:
            return None, rows
        healthy.sort(
            key=lambda row: (row.get("busy", True), -(row.get("free_mib", 0))),
        )
        return str(healthy[0]["base_url"]), rows

    def media_candidate_bases(self) -> tuple[list[str], list[dict]]:
        _, rows = self.choose_media_base()
        healthy = [row for row in rows if row.get("status") == "ok"]
        healthy.sort(
            key=lambda row: (row.get("busy", True), -(row.get("free_mib", 0))),
        )
        return [str(row["base_url"]) for row in healthy], rows

    def choose_transcribe_base(self) -> tuple[str | None, list[dict]]:
        rows: list[dict] = []
        for base in self.transcribe_bases:
            try:
                doc = self.fetch_json(base.rstrip("/") + "/health")
                row = {
                    "base_url": base,
                    "status": doc.get("status"),
                    "model": doc.get("model"),
                    "http_status": int(doc.get("_http_status") or 0),
                }
                rows.append(row)
            except Exception as exc:
                rows.append({"base_url": base, "status": "error", "error": str(exc)})
        healthy = [row for row in rows if row.get("status") == "ok"]
        if not healthy:
            return None, rows
        return str(healthy[0]["base_url"]), rows

    def transcribe_candidate_bases(self) -> tuple[list[str], list[dict]]:
        _, rows = self.choose_transcribe_base()
        healthy = [row for row in rows if row.get("status") == "ok"]
        return [str(row["base_url"]) for row in healthy], rows

    def choose_ocr_base(self) -> tuple[str | None, list[dict]]:
        rows: list[dict] = []
        for base in self.ocr_bases:
            try:
                doc = self.fetch_json(base.rstrip("/") + "/health")
                row = {
                    "base_url": base,
                    "status": doc.get("status"),
                    "engine": doc.get("engine"),
                    "family": doc.get("family"),
                    "default_tier": doc.get("default_tier"),
                    "device": doc.get("device"),
                    "supports": doc.get("supports") or [],
                    "http_status": int(doc.get("_http_status") or 0),
                }
                rows.append(row)
            except Exception as exc:
                rows.append({"base_url": base, "status": "error", "error": str(exc)})
        healthy = [row for row in rows if row.get("status") == "ok"]
        if not healthy:
            return None, rows
        healthy.sort(
            key=lambda row: (
                str(row.get("device") or "") != "cuda",
                str(row.get("base_url") or ""),
            )
        )
        return str(healthy[0]["base_url"]), rows

    def ocr_candidate_bases(self) -> tuple[list[str], list[dict]]:
        _, rows = self.choose_ocr_base()
        healthy = [row for row in rows if row.get("status") == "ok"]
        healthy.sort(
            key=lambda row: (
                str(row.get("device") or "") != "cuda",
                str(row.get("base_url") or ""),
            )
        )
        return [str(row["base_url"]) for row in healthy], rows

    def choose_rerank_base(self) -> tuple[str | None, list[dict]]:
        rows: list[dict] = []
        for base in self.rerank_bases:
            try:
                doc = self.fetch_json(base.rstrip("/") + "/health")
                row = {
                    "base_url": base,
                    "status": doc.get("status"),
                    "engine": doc.get("engine"),
                    "model": doc.get("model"),
                    "device": doc.get("device"),
                    "loaded": bool(doc.get("loaded")),
                    "supports": doc.get("supports") or [],
                    "http_status": int(doc.get("_http_status") or 0),
                }
                rows.append(row)
            except Exception as exc:
                rows.append({"base_url": base, "status": "error", "error": str(exc)})
        healthy = [row for row in rows if row.get("status") == "ok"]
        if not healthy:
            return None, rows
        healthy.sort(
            key=lambda row: (
                not bool(row.get("loaded")),
                str(row.get("device") or "") != "cuda",
                str(row.get("base_url") or ""),
            )
        )
        return str(healthy[0]["base_url"]), rows

    def rerank_candidate_bases(self) -> tuple[list[str], list[dict]]:
        _, rows = self.choose_rerank_base()
        healthy = [row for row in rows if row.get("status") == "ok"]
        healthy.sort(
            key=lambda row: (
                not bool(row.get("loaded")),
                str(row.get("device") or "") != "cuda",
                str(row.get("base_url") or ""),
            )
        )
        return [str(row["base_url"]) for row in healthy], rows

    def choose_safety_base(self) -> tuple[str | None, list[dict]]:
        rows: list[dict] = []
        for base in self.safety_bases:
            try:
                doc = self.fetch_json(base.rstrip("/") + "/health")
                row = {
                    "base_url": base,
                    "status": doc.get("status"),
                    "engine": doc.get("engine"),
                    "model": doc.get("model"),
                    "device": doc.get("device"),
                    "loaded": bool(doc.get("loaded")),
                    "supports": doc.get("supports") or [],
                    "http_status": int(doc.get("_http_status") or 0),
                }
                rows.append(row)
            except Exception as exc:
                rows.append({"base_url": base, "status": "error", "error": str(exc)})
        healthy = [row for row in rows if row.get("status") == "ok"]
        if not healthy:
            return None, rows
        healthy.sort(
            key=lambda row: (
                not bool(row.get("loaded")),
                str(row.get("device") or "") != "cuda",
                str(row.get("base_url") or ""),
            )
        )
        return str(healthy[0]["base_url"]), rows

    def safety_candidate_bases(self) -> tuple[list[str], list[dict]]:
        _, rows = self.choose_safety_base()
        healthy = [row for row in rows if row.get("status") == "ok"]
        healthy.sort(
            key=lambda row: (
                not bool(row.get("loaded")),
                str(row.get("device") or "") != "cuda",
                str(row.get("base_url") or ""),
            )
        )
        return [str(row["base_url"]) for row in healthy], rows

    def image_health_doc(self, base: str) -> dict | None:
        for path in ("/health", "/sdapi/v1/options"):
            doc = self.fetch_json_or_none(
                base.rstrip("/") + path,
                timeout_s=min(self.timeout_s, self.inventory_timeout_s),
            )
            if isinstance(doc, dict):
                doc["_health_path"] = path
                return doc
        return None

    def choose_image_base(self) -> tuple[str | None, list[dict]]:
        rows: list[dict] = []
        for base in self.image_bases:
            try:
                doc = self.image_health_doc(base)
                if not isinstance(doc, dict):
                    rows.append(
                        {
                            "base_url": base,
                            "status": "error",
                            "error": "no_health_response",
                        }
                    )
                    continue
                model = (
                    doc.get("model")
                    or doc.get("sd_model_checkpoint")
                    or doc.get("checkpoint")
                    or "stable-diffusion:configured-backend"
                )
                status = str(doc.get("status") or "").strip().lower()
                if not status:
                    status = "ok" if doc.get("_health_path") else "unknown"
                row = {
                    "base_url": base,
                    "status": status,
                    "engine": doc.get("engine") or "stable-diffusion",
                    "model": model,
                    "device": doc.get("device") or doc.get("cuda") or "",
                    "loaded": bool(doc.get("loaded", True)),
                    "health_path": doc.get("_health_path"),
                    "http_status": int(doc.get("_http_status") or 0),
                }
                rows.append(row)
            except Exception as exc:
                rows.append({"base_url": base, "status": "error", "error": str(exc)})
        healthy = [row for row in rows if row.get("status") == "ok"]
        if not healthy:
            return None, rows
        healthy.sort(
            key=lambda row: (
                not bool(row.get("loaded", True)),
                str(row.get("device") or "") != "cuda",
                str(row.get("base_url") or ""),
            )
        )
        return str(healthy[0]["base_url"]), rows

    def image_candidate_bases(self) -> tuple[list[str], list[dict]]:
        _, rows = self.choose_image_base()
        healthy = [row for row in rows if row.get("status") == "ok"]
        healthy.sort(
            key=lambda row: (
                not bool(row.get("loaded", True)),
                str(row.get("device") or "") != "cuda",
                str(row.get("base_url") or ""),
            )
        )
        return [str(row["base_url"]) for row in healthy], rows

    def combined_models(self) -> dict:
        merged: dict[tuple[str, str], dict] = {}
        for row in self.ollama_host_rows():
            base = str(row.get("base_url") or "")
            for model in row.get("model_docs") or []:
                model_id = str(model.get("id") or "").strip()
                if not model_id:
                    continue
                if model_id in HIDDEN_MODEL_IDS:
                    continue
                key = ("ollama", model_id)
                if key not in merged:
                    item = dict(model)
                    item["provider"] = "ollama"
                    item["host"] = base
                    item["hosts"] = [base]
                    merged[key] = item
                elif base not in merged[key]["hosts"]:
                    merged[key]["hosts"].append(base)
        for base in self.peer_bases:
            doc = self.fetch_json_or_none(
                base.rstrip("/") + "/api/tags",
                timeout_s=min(self.timeout_s, self.peer_timeout_s),
            )
            if doc is None:
                continue
            for model in doc.get("models") or []:
                if not isinstance(model, dict):
                    continue
                model_id = str(
                    model.get("model") or model.get("name") or model.get("id") or ""
                ).strip()
                if not model_id or model_id in HIDDEN_MODEL_IDS:
                    continue
                key = ("ollama", model_id)
                if key not in merged:
                    item = dict(model)
                    item["id"] = model_id
                    item["provider"] = "ollama"
                    item["host"] = base
                    item["hosts"] = [base]
                    item["peer_discovered"] = True
                    merged[key] = item
                elif base not in merged[key]["hosts"]:
                    merged[key]["hosts"].append(base)
        try:
            for row in self.ds4_host_rows():
                base = str(row.get("base_url") or "")
                for model in row.get("model_docs") or []:
                    model_id = str(model.get("id") or "").strip()
                    if not model_id:
                        continue
                    key = ("ds4", model_id)
                    if key not in merged:
                        item = dict(model)
                        item["provider"] = "ds4"
                        item["host"] = base
                        item["hosts"] = [base]
                        merged[key] = item
                    elif base not in merged[key]["hosts"]:
                        merged[key]["hosts"].append(base)
        except Exception:
            pass
        try:
            for row in self.ocr_candidate_bases()[1]:
                if row.get("status") != "ok":
                    continue
                model_id = f"paddleocr:{str(row.get('family') or 'PP-OCRv6')}-{str(row.get('default_tier') or 'small')}"
                key = ("ocr", model_id)
                base = str(row.get("base_url") or "")
                item = {
                    "id": model_id,
                    "object": "model",
                    "provider": "ocr",
                    "host": base,
                    "hosts": [base],
                    "capabilities": ["ocr", "document_parse", "vision"],
                    "access": "ocr_proxy",
                    "recommended_path": "/v1/ocr",
                    "summary": f"Local PaddleOCR lane on {row.get('device') or 'unknown'} for image and sampled-video OCR.",
                    "details": {
                        "engine": row.get("engine"),
                        "family": row.get("family"),
                        "default_tier": row.get("default_tier"),
                        "supports": row.get("supports") or [],
                    },
                }
                if key not in merged:
                    merged[key] = item
                elif base and base not in merged[key].get("hosts", []):
                    merged[key]["hosts"].append(base)
        except Exception:
            pass
        try:
            for row in self.rerank_candidate_bases()[1]:
                if row.get("status") != "ok":
                    continue
                raw_model = str(row.get("model") or "").strip()
                model_id = (
                    DEFAULT_RERANK_MODEL
                    if raw_model.startswith("/") or not raw_model
                    else raw_model
                )
                key = ("rerank", model_id)
                base = str(row.get("base_url") or "")
                item = {
                    "id": model_id,
                    "object": "model",
                    "provider": "rerank",
                    "host": base,
                    "hosts": [base],
                    "capabilities": ["rerank"],
                    "access": "rerank_proxy",
                    "recommended_path": "/v1/rerank",
                    "summary": "Local BGE cross-encoder rerank lane for evidence ordering before planner/cloud calls.",
                    "details": {
                        "engine": row.get("engine"),
                        "device": row.get("device"),
                        "loaded": bool(row.get("loaded")),
                        "supports": row.get("supports") or [],
                    },
                }
                if key not in merged:
                    merged[key] = item
                elif base and base not in merged[key].get("hosts", []):
                    merged[key]["hosts"].append(base)
        except Exception:
            pass
        try:
            for row in self.safety_candidate_bases()[1]:
                if row.get("status") != "ok":
                    continue
                raw_model = str(row.get("model") or "").strip()
                model_id = (
                    QWEN3GUARD_MODEL
                    if raw_model.startswith("/") or not raw_model
                    else raw_model
                )
                key = ("safety", model_id)
                base = str(row.get("base_url") or "")
                item = {
                    "id": model_id,
                    "object": "model",
                    "provider": "safety",
                    "host": base,
                    "hosts": [base],
                    "capabilities": ["safety", "prompt_injection"],
                    "access": "safety_proxy",
                    "recommended_path": "/v1/safety/classify",
                    "summary": "Local Qwen3Guard safety and prompt-injection classification lane.",
                    "details": {
                        "engine": row.get("engine"),
                        "device": row.get("device"),
                        "loaded": bool(row.get("loaded")),
                        "supports": row.get("supports") or [],
                    },
                }
                if key not in merged:
                    merged[key] = item
                elif base and base not in merged[key].get("hosts", []):
                    merged[key]["hosts"].append(base)
        except Exception:
            pass
        try:
            for row in self.image_candidate_bases()[1]:
                if row.get("status") != "ok":
                    continue
                raw_model = str(row.get("model") or "").strip()
                model_id = raw_model or "stable-diffusion:configured-backend"
                key = ("image", model_id)
                base = str(row.get("base_url") or "")
                item = {
                    "id": model_id,
                    "object": "model",
                    "provider": "image",
                    "host": base,
                    "hosts": [base],
                    "capabilities": ["image_generate"],
                    "access": "image_generation_proxy",
                    "recommended_path": "/v1/images/generations",
                    "summary": "Local Stable Diffusion-compatible image generation lane.",
                    "details": {
                        "engine": row.get("engine"),
                        "device": row.get("device"),
                        "loaded": bool(row.get("loaded")),
                        "health_path": row.get("health_path"),
                    },
                }
                if key not in merged:
                    merged[key] = item
                elif base and base not in merged[key].get("hosts", []):
                    merged[key]["hosts"].append(base)
        except Exception:
            pass
        try:
            for base in self.peer_bases:
                doc = self.fetch_json_or_none(
                    base.rstrip("/") + "/health",
                    timeout_s=min(self.timeout_s, self.peer_timeout_s),
                )
                if not isinstance(doc, dict):
                    continue
                for row in (doc.get("downstreams") or {}).get("ocr") or []:
                    if not isinstance(row, dict) or row.get("status") != "ok":
                        continue
                    model_id = f"paddleocr:{str(row.get('family') or 'PP-OCRv6')}-{str(row.get('default_tier') or 'small')}"
                    key = ("ocr", model_id)
                    item = {
                        "id": model_id,
                        "object": "model",
                        "provider": "ocr",
                        "host": base,
                        "hosts": [base],
                        "peer_discovered": True,
                        "capabilities": ["ocr", "document_parse", "vision"],
                        "access": "ocr_proxy",
                        "recommended_path": "/v1/ocr",
                        "summary": f"Peer PaddleOCR lane on {row.get('device') or 'unknown'} for image and sampled-video OCR.",
                        "details": {
                            "engine": row.get("engine"),
                            "family": row.get("family"),
                            "default_tier": row.get("default_tier"),
                            "supports": row.get("supports") or [],
                        },
                    }
                    if key not in merged:
                        merged[key] = item
                    elif base and base not in merged[key].get("hosts", []):
                        merged[key]["hosts"].append(base)
        except Exception:
            pass
        try:
            for base in self.peer_bases:
                doc = self.fetch_json_or_none(
                    base.rstrip("/") + "/health",
                    timeout_s=min(self.timeout_s, self.peer_timeout_s),
                )
                if not isinstance(doc, dict):
                    continue
                for row in (doc.get("downstreams") or {}).get("rerank") or []:
                    if not isinstance(row, dict) or row.get("status") != "ok":
                        continue
                    raw_model = str(row.get("model") or "").strip()
                    model_id = (
                        DEFAULT_RERANK_MODEL
                        if raw_model.startswith("/") or not raw_model
                        else raw_model
                    )
                    key = ("rerank", model_id)
                    item = {
                        "id": model_id,
                        "object": "model",
                        "provider": "rerank",
                        "host": base,
                        "hosts": [base],
                        "peer_discovered": True,
                        "capabilities": ["rerank"],
                        "access": "rerank_proxy",
                        "recommended_path": "/v1/rerank",
                        "summary": "Peer BGE cross-encoder rerank lane for evidence ordering before planner/cloud calls.",
                        "details": {
                            "engine": row.get("engine"),
                            "device": row.get("device"),
                            "loaded": bool(row.get("loaded")),
                            "supports": row.get("supports") or [],
                        },
                    }
                    if key not in merged:
                        merged[key] = item
                    elif base and base not in merged[key].get("hosts", []):
                        merged[key]["hosts"].append(base)
        except Exception:
            pass
        try:
            for base in self.peer_bases:
                doc = self.fetch_json_or_none(
                    base.rstrip("/") + "/health",
                    timeout_s=min(self.timeout_s, self.peer_timeout_s),
                )
                if not isinstance(doc, dict):
                    continue
                for row in (doc.get("downstreams") or {}).get("safety") or []:
                    if not isinstance(row, dict) or row.get("status") != "ok":
                        continue
                    raw_model = str(row.get("model") or "").strip()
                    model_id = (
                        QWEN3GUARD_MODEL
                        if raw_model.startswith("/") or not raw_model
                        else raw_model
                    )
                    key = ("safety", model_id)
                    item = {
                        "id": model_id,
                        "object": "model",
                        "provider": "safety",
                        "host": base,
                        "hosts": [base],
                        "peer_discovered": True,
                        "capabilities": ["safety", "prompt_injection"],
                        "access": "safety_proxy",
                        "recommended_path": "/v1/safety/classify",
                        "summary": "Peer Qwen3Guard safety and prompt-injection classification lane.",
                        "details": {
                            "engine": row.get("engine"),
                            "device": row.get("device"),
                            "loaded": bool(row.get("loaded")),
                            "supports": row.get("supports") or [],
                        },
                    }
                    if key not in merged:
                        merged[key] = item
                    elif base and base not in merged[key].get("hosts", []):
                        merged[key]["hosts"].append(base)
        except Exception:
            pass
        try:
            for base in self.peer_bases:
                doc = self.fetch_json_or_none(
                    base.rstrip("/") + "/health",
                    timeout_s=min(self.timeout_s, self.peer_timeout_s),
                )
                if not isinstance(doc, dict):
                    continue
                for row in (doc.get("downstreams") or {}).get("image") or []:
                    if not isinstance(row, dict) or row.get("status") != "ok":
                        continue
                    raw_model = str(row.get("model") or "").strip()
                    model_id = raw_model or "stable-diffusion:configured-backend"
                    key = ("image", model_id)
                    item = {
                        "id": model_id,
                        "object": "model",
                        "provider": "image",
                        "host": base,
                        "hosts": [base],
                        "peer_discovered": True,
                        "capabilities": ["image_generate"],
                        "access": "image_generation_proxy",
                        "recommended_path": "/v1/images/generations",
                        "summary": "Peer Stable Diffusion-compatible image generation lane.",
                        "details": {
                            "engine": row.get("engine"),
                            "device": row.get("device"),
                            "loaded": bool(row.get("loaded")),
                            "health_path": row.get("health_path"),
                        },
                    }
                    if key not in merged:
                        merged[key] = item
                    elif base and base not in merged[key].get("hosts", []):
                        merged[key]["hosts"].append(base)
        except Exception:
            pass
        data = sorted(
            merged.values(),
            key=lambda row: (str(row.get("provider") or ""), str(row.get("id") or "")),
        )
        return {"object": "list", "data": data}

    def public_models_doc(self) -> dict:
        rows: list[dict[str, object]] = []
        for row in self.combined_models().get("data") or []:
            model_row = dict(row)
            provider = str(model_row.get("provider") or "")
            model_row["provider"] = self.public_provider(provider)
            if not self.expose_upstream_details:
                model_row.pop("host", None)
                model_row.pop("hosts", None)
            rows.append(model_row)
        return {"object": "list", "data": rows}

    def recommended_path(
        self, provider: str, capabilities: list[str], access: str
    ) -> str:
        if provider == "ds4" or access.startswith("unified_chat"):
            return "/v1/chat/completions"
        if "transcribe" in capabilities:
            return "/transcribe"
        if "rerank" in capabilities:
            return "/v1/rerank"
        if "ocr" in capabilities or access == "ocr_proxy":
            return "/v1/ocr"
        if "safety" in capabilities or access == "safety_proxy":
            return "/v1/safety/classify"
        if "image_generate" in capabilities or access == "image_generation_proxy":
            return "/v1/images/generations"
        if "embed" in capabilities:
            return "/v1/embeddings"
        return "/ollama/v1/chat/completions"

    def feature_flags(self) -> dict[str, object]:
        public_endpoints = self.public_endpoints()
        return {
            "human_ui": True,
            "overview_doc": True,
            "ollama_root_compat": True,
            "prefetch_api": True,
            "evict_api": True,
            "request_ids": True,
            "priority_hints": True,
            "priority_queue": False,
            "async_jobs": True,
            "prefetch_jobs": True,
            "structured_logging": True,
            "recent_activity": True,
            "ocr_proxy": True,
            "native_rerank_proxy": True,
            "safety_proxy": True,
            "image_generation_api": True,
            "gateway_only_broadcast": not self.expose_upstream_details
            and not self.advertise_aux_services,
            "upstream_details_public": self.expose_upstream_details,
            "aux_service_broadcast": self.advertise_aux_services,
            "peer_failover": bool(self.peer_bases),
            "peer_loop_guard": self.max_peer_hops,
            "head_support": [
                str(item["path"])
                for item in public_endpoints
                if "HEAD" in (item.get("methods") or [])
            ],
        }

    def load_published_packets(
        self,
    ) -> tuple[dict[str, object] | None, str, dict[str, object] | None, str]:
        benchmark_doc, benchmark_path = read_first_json_doc(self.benchmark_packet_paths)
        preflight_doc, preflight_path = read_first_json_doc(self.preflight_packet_paths)
        return benchmark_doc, benchmark_path, preflight_doc, preflight_path

    def benchmark_contract_lookup(
        self, benchmark_doc: dict[str, object] | None
    ) -> dict[str, dict[str, object]]:
        if not isinstance(benchmark_doc, dict):
            return {}
        rows = [
            apply_live_policy_contract_override(row)
            for row in (benchmark_doc.get("capability_contracts") or [])
            if isinstance(row, dict)
        ]
        return {
            str(row.get("contract_id") or ""): row
            for row in rows
            if str(row.get("contract_id") or "").strip()
        }

    def capability_contract_doc(self, contract_id: str) -> dict[str, object] | None:
        benchmark_doc, benchmark_path, _preflight_doc, _preflight_path = (
            self.load_published_packets()
        )
        lookup = self.benchmark_contract_lookup(benchmark_doc)
        clean = str(contract_id or "").strip().lower().replace("-", "_")
        aliases: dict[str, str] = {}
        for row_id, row in lookup.items():
            aliases[row_id.lower().replace("-", "_")] = row_id
            for alias in row.get("aliases") or []:
                aliases[str(alias).strip().lower().replace("-", "_")] = row_id
        resolved = aliases.get(clean, clean)
        row = lookup.get(resolved)
        if not row:
            return None
        return {
            "schema": "norllama.capability-contract.v1",
            "service": "norllama",
            "time": now_iso(),
            "source": {
                "kind": (
                    "benchmark_packet_with_live_policy_override"
                    if row.get("live_policy_override")
                    else "benchmark_packet"
                ),
                "path": benchmark_path,
                "generated_at": str((benchmark_doc or {}).get("generated_at") or ""),
            },
            "contract": row,
            "usage": {
                "dispatch": str(row.get("dispatch") or "unified_chat"),
                "guardrail": str(row.get("guardrail") or ""),
                "default_profile": str(row.get("default_profile") or ""),
                "default_model": str(row.get("default_model") or ""),
            },
        }

    def warm_policy_contract_lanes(self, contract: dict[str, object]) -> list[str]:
        keys = [
            str(contract.get("contract_id") or "").strip().lower().replace("-", "_")
        ]
        for alias in contract.get("aliases") or []:
            keys.append(str(alias or "").strip().lower().replace("-", "_"))
        lanes: list[str] = []
        for key in keys:
            for lane in WARM_POLICY_CONTRACT_LANES.get(key, ()):
                if lane and lane not in lanes:
                    lanes.append(lane)
        return [lane for lane in lanes if lane in WARM_POLICY_LANES]

    def warm_policy_contract_models(
        self, contract: dict[str, object]
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        default_model = str(
            contract.get("default_model") or contract.get("model") or ""
        ).strip()
        if default_model:
            rows.append(
                {
                    "model": default_model,
                    "role": "default",
                    "profile": str(
                        contract.get("default_profile") or contract.get("profile") or ""
                    ),
                    "score": contract.get("best_weighted_score"),
                }
            )
        for alternate in contract.get("alternates") or []:
            if not isinstance(alternate, dict):
                continue
            model = str(alternate.get("model") or alternate.get("name") or "").strip()
            if not model:
                continue
            rows.append(
                {
                    "model": model,
                    "role": "alternate",
                    "profile": str(alternate.get("profile") or ""),
                    "score": alternate.get("best_weighted_score")
                    or alternate.get("score"),
                    "suite_count": alternate.get("suite_count"),
                }
            )
        for hit in contract.get("suite_hits") or []:
            if not isinstance(hit, dict):
                continue
            model = str(hit.get("model") or hit.get("name") or "").strip()
            if not model:
                continue
            rows.append(
                {
                    "model": model,
                    "role": "suite_hit",
                    "profile": str(hit.get("profile") or ""),
                    "score": hit.get("avg_score") or hit.get("best_weighted_score"),
                    "suite_id": hit.get("suite_id"),
                    "coverage_ratio": hit.get("coverage_ratio"),
                    "route_recommendation": hit.get("route_recommendation"),
                }
            )
        deduped: list[dict[str, object]] = []
        seen: set[str] = set()
        for row in rows:
            model = str(row.get("model") or "").strip()
            key = model.lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        return deduped

    def warm_policy_model_observe_only(self, model: str) -> bool:
        clean = str(model or "").strip().lower()
        return bool(
            clean
            and any(
                needle and needle in clean
                for needle in WARM_POLICY_OBSERVE_ONLY_MODEL_NEEDLES
            )
        )

    def warm_policy_entry(
        self,
        contract: dict[str, object],
        model_row: dict[str, object],
        *,
        action: str,
        authority: str,
        state: str,
        available: bool,
        active: bool,
        hosts: list[str],
        active_hosts: list[str] | None = None,
    ) -> dict[str, object]:
        dispatch = str(contract.get("dispatch") or "unified_chat").strip()
        score = model_row.get("score")
        if score in (None, ""):
            score = contract.get("best_weighted_score")
        return {
            "model": str(model_row.get("model") or "").strip(),
            "contract_id": str(contract.get("contract_id") or "").strip(),
            "contract_status": state,
            "dispatch": dispatch,
            "selection_method": str(contract.get("selection_method") or "").strip(),
            "action": action,
            "priority": "p0" if authority != "canary_health_only" else "canary",
            "available": bool(available),
            "active": bool(active),
            "hosts": hosts,
            "active_hosts": active_hosts or [],
            "benchmark_quality": {
                "eligible": authority not in {"blocked", "canary_health_only"},
                "state": state,
                "reason": str(
                    contract.get("guardrail") or state or "benchmark contract"
                )[:240],
                "score": score,
                "coverage_ratio": model_row.get("coverage_ratio"),
            },
            "authority": authority,
            "chat_candidate": dispatch not in WARM_POLICY_TOOL_ONLY_DISPATCHES,
            "model_role": str(model_row.get("role") or "").strip(),
            "profile": str(model_row.get("profile") or "").strip(),
        }

    def warm_policy_dedupe_entries(
        self, entries: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        deduped: list[dict[str, object]] = []
        seen: set[str] = set()
        for entry in entries:
            key = "|".join(
                [
                    str(entry.get("model") or "").strip().lower(),
                    str(entry.get("contract_id") or "").strip().lower(),
                    str(entry.get("dispatch") or "").strip().lower(),
                    str(entry.get("authority") or "").strip().lower(),
                ]
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(
                {
                    key: value
                    for key, value in entry.items()
                    if value is not None and value != "" and value != []
                }
            )
        return deduped

    def warm_policy_doc(self) -> dict[str, object]:
        benchmark_doc, benchmark_path, _preflight_doc, _preflight_path = (
            self.load_published_packets()
        )
        contracts = list(self.benchmark_contract_lookup(benchmark_doc).values())
        catalog_doc = self.public_models_doc()
        catalog_rows = [
            row for row in (catalog_doc.get("data") or []) if isinstance(row, dict)
        ]
        catalog: dict[str, dict[str, object]] = {}
        for row in catalog_rows:
            model_id = str(
                row.get("id") or row.get("model") or row.get("name") or ""
            ).strip()
            if model_id and model_id.lower() not in catalog:
                catalog[model_id.lower()] = row
        ps_doc = self.merged_ollama_ps(include_peers=True)
        active_hosts_by_model: dict[str, list[str]] = {}
        for row in ps_doc.get("models") or []:
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("model") or row.get("name") or "").strip().lower()
            if not model_id:
                continue
            host = str(row.get("gateway_host") or row.get("host") or "").strip()
            if host:
                active_hosts_by_model.setdefault(model_id, [])
                if host not in active_hosts_by_model[model_id]:
                    active_hosts_by_model[model_id].append(host)
            else:
                active_hosts_by_model.setdefault(model_id, [])
        active_models = set(active_hosts_by_model)
        prefetch_doc = self.prefetch_jobs_doc(limit=50)
        warming_models = {
            str(row.get("model") or "").strip().lower()
            for row in prefetch_doc.get("items") or []
            if isinstance(row, dict)
            and str(row.get("status") or "") in {"queued", "running", "warm"}
            and str(row.get("model") or "").strip()
        }
        lanes: dict[str, dict[str, object]] = {
            lane: {
                "lane": lane,
                "eligible_models": [],
                "blocked_models": [],
                "canary_models": [],
            }
            for lane in WARM_POLICY_LANES
        }
        for contract in contracts:
            lane_ids = self.warm_policy_contract_lanes(contract)
            if not lane_ids:
                continue
            status = (
                str(
                    contract.get("status") or contract.get("benchmark_confidence") or ""
                )
                .strip()
                .lower()
            )
            dispatch = str(contract.get("dispatch") or "unified_chat").strip()
            model_rows = self.warm_policy_contract_models(contract)
            if not model_rows:
                entry = self.warm_policy_entry(
                    contract,
                    {"model": ""},
                    action="skip_missing_model",
                    authority="blocked",
                    state=status or "missing_model",
                    available=False,
                    active=False,
                    hosts=[],
                )
                for lane in lane_ids:
                    lanes[lane]["blocked_models"].append(entry)
                continue
            for model_row in model_rows:
                model = str(model_row.get("model") or "").strip()
                catalog_row = catalog.get(model.lower()) or {}
                available = bool(catalog_row)
                active = model.lower() in active_models
                active_hosts = active_hosts_by_model.get(model.lower(), [])
                warming = model.lower() in warming_models
                hosts = [
                    str(host)
                    for host in (catalog_row.get("hosts") or [])
                    if str(host or "").strip()
                ]
                if not hosts and str(catalog_row.get("host") or "").strip():
                    hosts = [str(catalog_row.get("host"))]
                tool_only = dispatch in WARM_POLICY_TOOL_ONLY_DISPATCHES
                if (
                    self.warm_policy_model_observe_only(model)
                    or status in WARM_POLICY_CANARY_STATUSES
                ):
                    entry = self.warm_policy_entry(
                        contract,
                        model_row,
                        action="observe",
                        authority="canary_health_only",
                        state=status or "canary",
                        available=available,
                        active=active,
                        hosts=hosts,
                        active_hosts=active_hosts,
                    )
                    for lane in lane_ids:
                        lanes[lane]["canary_models"].append(entry)
                    continue
                if status not in WARM_POLICY_READY_STATUSES:
                    entry = self.warm_policy_entry(
                        contract,
                        model_row,
                        action="skip_quality_gate",
                        authority="blocked",
                        state=status or "unverified",
                        available=available,
                        active=active,
                        hosts=hosts,
                        active_hosts=active_hosts,
                    )
                    for lane in lane_ids:
                        lanes[lane]["blocked_models"].append(entry)
                    continue
                if not available:
                    entry = self.warm_policy_entry(
                        contract,
                        model_row,
                        action="skip_unavailable",
                        authority="blocked",
                        state=status or "benchmark_backed",
                        available=False,
                        active=False,
                        hosts=[],
                    )
                    for lane in lane_ids:
                        lanes[lane]["blocked_models"].append(entry)
                    continue
                action = (
                    "tool_lane"
                    if tool_only
                    else "keep_warm"
                    if active
                    else "warming"
                    if warming
                    else "prefetch"
                )
                authority = "tool_lane_only" if tool_only else "preflight_or_draft"
                entry = self.warm_policy_entry(
                    contract,
                    model_row,
                    action=action,
                    authority=authority,
                    state=status or "benchmark_backed",
                    available=True,
                    active=active,
                    hosts=hosts,
                    active_hosts=active_hosts,
                )
                for lane in lane_ids:
                    lanes[lane]["eligible_models"].append(entry)
        prefetch_candidates: list[dict[str, object]] = []
        for lane, summary in lanes.items():
            summary["eligible_models"] = self.warm_policy_dedupe_entries(
                list(summary["eligible_models"])
            )
            summary["blocked_models"] = self.warm_policy_dedupe_entries(
                list(summary["blocked_models"])
            )
            summary["canary_models"] = self.warm_policy_dedupe_entries(
                list(summary["canary_models"])
            )
            summary["eligible_count"] = len(summary["eligible_models"])
            summary["blocked_count"] = len(summary["blocked_models"])
            summary["canary_count"] = len(summary["canary_models"])
            if any(row.get("active") for row in summary["eligible_models"]):
                summary["status"] = "ready"
            elif any(
                row.get("action") in {"prefetch", "warming"}
                for row in summary["eligible_models"]
            ):
                summary["status"] = "prefetch_or_wait"
            elif summary["eligible_count"]:
                summary["status"] = "tool_ready"
            elif summary["canary_count"]:
                summary["status"] = "canary"
            elif summary["blocked_count"]:
                summary["status"] = "blocked"
            else:
                summary["status"] = "unknown"
            for row in summary["eligible_models"]:
                if (
                    row.get("action") == "prefetch"
                    and row.get("chat_candidate") is not False
                ):
                    prefetch_candidates.append(
                        {
                            "lane": lane,
                            "model": row.get("model"),
                            "contract_id": row.get("contract_id"),
                            "hosts": row.get("hosts") or [],
                            "priority": row.get("priority") or "p0",
                            "source": "/v1/warm-policy",
                        }
                    )
        ready_lanes = [
            lane for lane, row in lanes.items() if row.get("status") == "ready"
        ]
        wait_lanes = [
            lane
            for lane, row in lanes.items()
            if row.get("status") == "prefetch_or_wait"
        ]
        if ready_lanes:
            route_posture = "ready"
        elif wait_lanes:
            route_posture = "prefetch_or_wait"
        elif any(row.get("status") == "canary" for row in lanes.values()):
            route_posture = "canary_only"
        else:
            route_posture = "blocked"
        return {
            "schema": "norllama.warm-policy.v1",
            "service": "norllama",
            "gateway": gateway_identity(),
            "time": now_iso(),
            "status": "ok" if contracts else "missing_benchmark_packet",
            "route_posture": route_posture,
            "residency_posture": "warm"
            if active_models
            else "warming"
            if warming_models
            else "cold",
            "source": {
                "kind": "benchmark_packet",
                "path": benchmark_path,
                "generated_at": str((benchmark_doc or {}).get("generated_at") or ""),
            },
            "catalog": {
                "visible_model_count": len(catalog_rows),
                "active_model_count": len(active_models),
            },
            "route_guardrails": {
                "schema": "norman.norllama.route-guardrail-matrix.v1",
                "source": "/v1/warm-policy",
                "selection_method": "norllama_benchmark_contracts",
                "lanes": lanes,
            },
            "prefetch_candidates": prefetch_candidates,
            "prefetch_jobs": prefetch_doc,
            "counts": {
                "contracts": len(contracts),
                "ready_lanes": len(ready_lanes),
                "prefetch_or_wait_lanes": len(wait_lanes),
                "prefetch": len(prefetch_candidates),
            },
        }

    def published_notes(self) -> dict[str, object]:
        benchmark_doc, benchmark_path, preflight_doc, preflight_path = (
            self.load_published_packets()
        )
        sources: list[dict[str, object]] = []
        if benchmark_doc is not None:
            sources.append(
                {
                    "kind": "benchmark_packet",
                    "path": benchmark_path,
                    "generated_at": str(benchmark_doc.get("generated_at") or ""),
                }
            )
        if preflight_doc is not None:
            sources.append(
                {
                    "kind": "preflight_packet",
                    "path": preflight_path,
                    "generated_at": str(preflight_doc.get("generated_at") or ""),
                }
            )
        if benchmark_doc is None and preflight_doc is None:
            return {
                "published": False,
                "sources": [],
                "benchmark_gaps": [],
                "agent_notes": [
                    "No published Norllama benchmark packet is available on this gateway."
                ],
                "coder_notes": [],
                "warm_set": {"local_profiles": [], "profiles": []},
            }
        aggregate = (
            benchmark_doc.get("aggregate") if isinstance(benchmark_doc, dict) else {}
        )
        warm_set = (
            benchmark_doc.get("warm_set") if isinstance(benchmark_doc, dict) else {}
        )
        return {
            "published": True,
            "sources": sources,
            "benchmark_gaps": list((benchmark_doc or {}).get("gaps") or []),
            "agent_notes": [
                "Benchmark-backed capability contracts are loaded from the published packet.",
                (
                    f"Valid benchmark rows: {int((aggregate or {}).get('total_answer_count') or 0)} "
                    f"of {int((aggregate or {}).get('total_attempt_count') or 0)} attempts; "
                    f"runtime failures retained separately: {int((aggregate or {}).get('total_runtime_failures') or 0)}."
                    if isinstance(aggregate, dict)
                    else "Benchmark aggregate unavailable."
                ),
            ],
            "coder_notes": [
                "Use /v1/capabilities/{contract} for benchmark-backed routing defaults.",
            ],
            "warm_set": warm_set
            if isinstance(warm_set, dict)
            else {"local_profiles": [], "profiles": []},
        }

    def capabilities_doc(self) -> dict:
        response_headers = {
            "X-Norllama-Request-Id": "Gateway request id for tracing.",
            "X-Norllama-Priority-Applied": "Normalized priority hint accepted by the gateway.",
        }
        if self.expose_upstream_details:
            response_headers["X-Norllama-Upstream"] = (
                "Chosen upstream for proxied work when applicable."
            )
            response_headers["X-Norllama-Attempts"] = (
                "Comma-separated upstream attempt chain for failover paths."
            )
        benchmark_doc, benchmark_path, preflight_doc, preflight_path = (
            self.load_published_packets()
        )
        contracts = list(self.benchmark_contract_lookup(benchmark_doc).values())
        sources: list[dict[str, object]] = []
        if benchmark_doc is not None:
            sources.append(
                {
                    "kind": "benchmark_packet",
                    "path": benchmark_path,
                    "generated_at": str(benchmark_doc.get("generated_at") or ""),
                }
            )
        if preflight_doc is not None:
            sources.append(
                {
                    "kind": "preflight_packet",
                    "path": preflight_path,
                    "generated_at": str(preflight_doc.get("generated_at") or ""),
                }
            )
        endpoints = self.public_endpoints()
        endpoint_kinds = {
            str(row.get("kind") or "").strip()
            for row in endpoints
            if str(row.get("kind") or "").strip()
        }
        tool_lanes: list[str] = []
        for kind, lanes in {
            "embedding": ("embed",),
            "rerank": ("rerank",),
            "safety": ("prompt_injection", "safety"),
            "ocr": ("doc_parse", "ocr"),
            "asr": ("asr", "stt"),
            "media": ("doc_parse", "gui_ground", "ocr"),
            "image_generate": ("image_generate",),
        }.items():
            if kind in endpoint_kinds:
                for lane in lanes:
                    if lane not in tool_lanes:
                        tool_lanes.append(lane)
        task_kinds = list(tool_lanes)
        if "unified_chat" in endpoint_kinds:
            task_kinds = ["chat", "plan", "code", *task_kinds]
        modalities = ["text"]
        if endpoint_kinds.intersection({"image_generate", "media", "ocr"}):
            modalities.append("image")
        if endpoint_kinds.intersection({"media", "ocr"}):
            modalities.extend(["file", "pdf"])
        if "asr" in endpoint_kinds:
            modalities.append("audio")
        return {
            "service": "norllama",
            "gateway": gateway_identity(),
            "time": now_iso(),
            "features": self.feature_flags(),
            "sources": sources,
            "contracts": contracts,
            "tool_lanes": tool_lanes,
            "task_kinds": unique_items(task_kinds),
            "modalities": unique_items(modalities),
            "model_policy": {
                "schema": "norllama.model-policy.v1",
                "mode": "qwen_first_local",
                "frontdoor": "https://llm.home.arpa",
                "preferred_chat_model": QWEN36_ROUTER_MODEL,
                "preferred_code_model": QWEN36_CODE_MODEL,
                "heavyweight_judge_model": QWEN35_JUDGE_MODEL,
                "embedding_model": DEFAULT_EMBEDDING_MODEL,
                "rerank_model": DEFAULT_RERANK_MODEL,
                "safety_model": QWEN3GUARD_MODEL,
                "policy_override_reason": LIVE_POLICY_OVERRIDE_REASON,
                "production_rule": (
                    "Catalog-only models are not production defaults until live inventory, smoke tests, "
                    "benchmark evidence, and route receipts agree."
                ),
            },
            "high_payback_model_lanes": HIGH_PAYBACK_MODEL_LANES,
            "default_contract": "chat"
            if any(str(row.get("contract_id") or "") == "chat" for row in contracts)
            else "",
            "human_ui": {
                "enabled": True,
                "paths": ["/", "/ui"],
                "local_only": self.bind in {"127.0.0.1", "localhost"},
            },
            "headers": {
                "request": {
                    "X-Request-Id": "Optional client-supplied request id. Norllama generates one when absent.",
                    "X-Norllama-Priority": {
                        "accepted": sorted(PRIORITY_LEVELS),
                        "mode": "hint_only",
                        "default": "normal",
                    },
                },
                "response": response_headers,
            },
            "async": {
                "supported": True,
                "mode": "prefetch_jobs",
                "notes": (
                    "Chat and passthrough inference are synchronous. Prefetch returns a job id and warms models in the background."
                    if not self.advertise_aux_services
                    else "Media, transcribe, and chat are immediate passthrough/failover today. Prefetch returns a job id and warms models in the background."
                ),
            },
            "priority": {
                "supported": True,
                "mode": "hint_only",
                "levels": sorted(PRIORITY_LEVELS),
                "notes": "Priority is exposed in headers and logs now. It does not yet reorder execution.",
            },
            "endpoints": endpoints,
        }

    def catalog(self) -> dict:
        models: list[dict[str, object]] = []
        for row in self.combined_models().get("data") or []:
            model_id = str(row.get("id") or "")
            provider = str(row.get("provider") or "")
            hosts = [str(item) for item in (row.get("hosts") or [])]
            capabilities = infer_model_capabilities(model_id, provider)
            access = infer_model_access(model_id, provider, capabilities)
            model_row: dict[str, object] = {
                "id": model_id,
                "provider": self.public_provider(provider),
                "capabilities": capabilities,
                "access": access,
                "recommended_path": self.recommended_path(
                    provider, capabilities, access
                ),
                "supports_stream": access.startswith("unified_chat"),
                "priority_hint_supported": True,
                "async_supported": False,
                "summary": self.public_summary(
                    provider,
                    capabilities,
                    infer_model_summary(model_id, provider, capabilities),
                ),
                "replica_count": len(hosts),
            }
            if self.expose_upstream_details:
                model_row["hosts"] = hosts
            models.append(model_row)
        return {
            "service": "norllama",
            "gateway": gateway_identity(),
            "time": now_iso(),
            "features": self.feature_flags(),
            "models": models,
            "published_notes": self.published_notes(),
        }

    def host_alias(self, base_url: str) -> str:
        host = (urllib.parse.urlparse(base_url).hostname or base_url).strip()
        if host.startswith("192.168.2."):
            suffix = host.rsplit(".", 1)[-1]
            if suffix.isdigit():
                return f"spark{suffix}"
        return host

    def catalog_summary(self, models: list[dict[str, object]]) -> dict[str, object]:
        providers: dict[str, int] = {}
        capabilities: dict[str, int] = {}
        access_modes: dict[str, int] = {}
        chat_models = 0
        specialized_models = 0
        for row in models:
            provider = str(row.get("provider") or "unknown")
            access = str(row.get("access") or "unknown")
            providers[provider] = providers.get(provider, 0) + 1
            access_modes[access] = access_modes.get(access, 0) + 1
            if access.startswith("unified_chat"):
                chat_models += 1
            else:
                specialized_models += 1
            for capability in row.get("capabilities") or []:
                cap = str(capability).strip()
                if not cap:
                    continue
                capabilities[cap] = capabilities.get(cap, 0) + 1
        return {
            "visible_model_count": len(models),
            "hidden_model_count": len(HIDDEN_MODEL_IDS),
            "providers": providers,
            "capabilities": capabilities,
            "access_modes": access_modes,
            "chat_models": chat_models,
            "specialized_models": specialized_models,
        }

    def fleet_rows(self, health: dict) -> list[dict[str, object]]:
        routing = health.get("routing") or {}
        downstreams = health.get("downstreams") or {}
        ollama_rows = {
            str(row.get("base_url") or ""): row
            for row in downstreams.get("ollama") or []
            if str(row.get("base_url") or "")
        }
        media_rows = {
            str(row.get("base_url") or ""): row
            for row in downstreams.get("media") or []
            if str(row.get("base_url") or "")
        }
        transcribe_rows = {
            str(row.get("base_url") or ""): row
            for row in downstreams.get("transcribe") or []
            if str(row.get("base_url") or "")
        }
        image_rows = {
            str(row.get("base_url") or ""): row
            for row in downstreams.get("image") or []
            if str(row.get("base_url") or "")
        }
        ds4_rows_raw = downstreams.get("ds4") or []
        if isinstance(ds4_rows_raw, list):
            ds4_rows = {
                str(row.get("base_url") or ""): row
                for row in ds4_rows_raw
                if str(row.get("base_url") or "")
            }
        else:
            ds4_rows = {}
        bases = {
            *(base for base in ollama_rows if base),
            *(base for base in media_rows if base),
            *(base for base in transcribe_rows if base),
            *(base for base in image_rows if base),
            *(base for base in ds4_rows if base),
        }
        merged: dict[str, dict[str, object]] = {}
        for base in sorted(bases, key=self.host_alias):
            label = self.host_alias(base)
            row = merged.setdefault(
                label,
                {
                    "label": label,
                    "base_url": base,
                    "selected_lanes": [],
                    "ollama": {
                        "healthy": False,
                        "http_status": 0,
                        "model_count": 0,
                        "loaded_models": None,
                    },
                    "media": {
                        "status": "unknown",
                        "busy": False,
                        "free_mib": 0,
                    },
                    "transcribe": {
                        "status": "unknown",
                        "model": "",
                    },
                    "image": {
                        "status": "unknown",
                        "model": "",
                    },
                    "ds4": {
                        "healthy": False,
                        "models": [],
                    },
                },
            )
            if (
                str(routing.get("ollama") or "") == base
                and "ollama" not in row["selected_lanes"]
            ):
                row["selected_lanes"].append("ollama")
            if (
                str(routing.get("media") or "") == base
                and "media" not in row["selected_lanes"]
            ):
                row["selected_lanes"].append("media")
            if (
                str(routing.get("transcribe") or "") == base
                and "transcribe" not in row["selected_lanes"]
            ):
                row["selected_lanes"].append("transcribe")
            if (
                str(routing.get("image") or "") == base
                and "image" not in row["selected_lanes"]
            ):
                row["selected_lanes"].append("image")
            if (
                str(routing.get("ds4") or "") == base
                and "ds4" not in row["selected_lanes"]
            ):
                row["selected_lanes"].append("ds4")
            if base in ollama_rows:
                ollama = ollama_rows.get(base) or {}
                row["ollama"] = {
                    "healthy": bool(ollama.get("healthy")),
                    "http_status": int(ollama.get("http_status") or 0),
                    "model_count": int(ollama.get("model_count") or 0),
                    "loaded_models": ollama.get("loaded_models"),
                }
            if base in media_rows:
                media = media_rows.get(base) or {}
                row["media"] = {
                    "status": str(media.get("status") or "unknown"),
                    "busy": bool(media.get("busy")),
                    "free_mib": int(media.get("free_mib") or 0),
                }
            if base in transcribe_rows:
                transcribe = transcribe_rows.get(base) or {}
                row["transcribe"] = {
                    "status": str(transcribe.get("status") or "unknown"),
                    "model": str(transcribe.get("model") or ""),
                }
            if base in image_rows:
                image = image_rows.get(base) or {}
                row["image"] = {
                    "status": str(image.get("status") or "unknown"),
                    "model": str(image.get("model") or ""),
                }
            if base in ds4_rows:
                ds4 = ds4_rows.get(base) or {}
                row["ds4"] = {
                    "healthy": bool(ds4.get("healthy")),
                    "models": list(ds4.get("models") or []),
                }
        return list(merged.values())

    def overview(self) -> dict:
        health = self.health()
        catalog_doc = self.catalog()
        recent = self.recent_activity(12)
        models = list(catalog_doc.get("models") or [])
        summary = self.catalog_summary(models)
        capabilities = self.capabilities_doc()
        endpoints = list(capabilities.get("endpoints") or [])
        highlights = [
            row
            for row in models
            if str(row.get("access") or "").startswith("unified_chat")
        ][:8]
        doc = {
            "service": "norllama",
            "gateway": gateway_identity(),
            "status": str(health.get("status") or "unknown"),
            "time": now_iso(),
            "catalog_summary": summary,
            "model_highlights": highlights,
            "recent_activity": recent,
            "contract": {
                "async_mode": "prefetch_jobs",
                "priority_mode": "hint_only",
                "structured_logging": True,
                "request_ids": True,
                "head_support_count": len(
                    self.feature_flags().get("head_support") or []
                ),
            },
            "endpoints": endpoints,
        }
        if self.expose_upstream_details:
            doc["routing"] = health.get("routing") or {}
            doc["fleet"] = self.fleet_rows(health)
            doc["health"] = health
        return doc

    def record_activity(self, record: dict[str, object]) -> None:
        with self._lock:
            self._recent_activity.append(record)
            if len(self._recent_activity) > self.activity_limit:
                self._recent_activity = self._recent_activity[-self.activity_limit :]
            if self._counts_as_tool_activity(record):
                self._recent_tool_activity.append(record)
                if len(self._recent_tool_activity) > self.tool_activity_limit:
                    self._recent_tool_activity = self._recent_tool_activity[
                        -self.tool_activity_limit :
                    ]

    def _counts_as_tool_activity(self, record: dict[str, object]) -> bool:
        method = str(record.get("method") or "").strip().upper() or "GET"
        path = str(record.get("path") or "").split("?", 1)[0].strip()
        capability = str(record.get("capability") or "").strip()
        if method in {"GET", "HEAD"}:
            return False
        if capability:
            return True
        return path in {
            "/api/chat",
            "/api/generate",
            "/api/embed",
            "/api/embeddings",
            "/v1/embeddings",
            "/v1/rerank",
            "/rerank",
            "/v1/safety/classify",
            "/safety/classify",
            "/v1/audio/transcriptions",
            "/transcribe",
            "/v1/ocr",
            "/ocr",
            "/v1/images/generations",
            "/v1/chat/completions",
            "/v1/prefetch",
            "/v1/evict",
        } or path.startswith("/media/")

    def recent_activity(self, limit: int = 20, *, tool_only: bool = False) -> dict:
        retention_limit = self.tool_activity_limit if tool_only else self.activity_limit
        safe_limit = max(1, min(limit, retention_limit))
        with self._lock:
            source_rows = (
                self._recent_tool_activity if tool_only else self._recent_activity
            )
            rows = list(source_rows[-safe_limit:])
        rows.reverse()
        return {
            "service": "norllama",
            "schema": "norllama.activity.v1",
            "time": now_iso(),
            "tool_only": bool(tool_only),
            "count": len(rows),
            "retention_limit": retention_limit,
            "items": [self.public_activity_item(row) for row in rows],
        }

    def _prefetch_job_key(
        self,
        *,
        kind: str,
        base_url: str,
        model: str,
        keep_alive: str,
        num_ctx: int | None,
    ) -> str:
        return "|".join(
            [
                kind,
                normalize_base_url(base_url),
                model,
                keep_alive,
                str(num_ctx or ""),
            ]
        )

    def _prune_prefetch_jobs_locked(self) -> None:
        now = time.time()
        ttl = max(60.0, float(self.prefetch_job_ttl_s or DEFAULT_PREFETCH_JOB_TTL_S))
        stale_ids = [
            job_id
            for job_id, job in self._prefetch_jobs.items()
            if now - float(job.get("updated_ts") or job.get("created_ts") or now) > ttl
            and str(job.get("status") or "") not in {"queued", "running"}
        ]
        for job_id in stale_ids:
            job = self._prefetch_jobs.pop(job_id, None) or {}
            key = str(job.get("key") or "")
            if key and self._prefetch_job_keys.get(key) == job_id:
                self._prefetch_job_keys.pop(key, None)
        limit = max(10, int(self.prefetch_job_limit or DEFAULT_PREFETCH_JOB_LIMIT))
        if len(self._prefetch_jobs) <= limit:
            return
        ordered = sorted(
            self._prefetch_jobs.items(),
            key=lambda item: float(
                item[1].get("updated_ts") or item[1].get("created_ts") or 0
            ),
        )
        for job_id, job in ordered[: max(0, len(self._prefetch_jobs) - limit)]:
            if str(job.get("status") or "") in {"queued", "running"}:
                continue
            self._prefetch_jobs.pop(job_id, None)
            key = str(job.get("key") or "")
            if key and self._prefetch_job_keys.get(key) == job_id:
                self._prefetch_job_keys.pop(key, None)

    def _public_prefetch_job(self, job: dict[str, object]) -> dict[str, object]:
        row = dict(job)
        if not self.expose_upstream_details:
            for key in ("upstream", "upstream_path", "attempts"):
                row.pop(key, None)
        for key in ("key", "request_body"):
            row.pop(key, None)
        return row

    def prefetch_jobs_doc(
        self,
        *,
        job_id: str = "",
        model: str = "",
        limit: int = 20,
    ) -> dict[str, object]:
        safe_limit = max(1, min(int(limit or 20), self.prefetch_job_limit))
        clean_job_id = str(job_id or "").strip()
        clean_model = str(model or "").strip()
        with self._lock:
            self._prune_prefetch_jobs_locked()
            jobs = list(self._prefetch_jobs.values())
        if clean_job_id:
            jobs = [job for job in jobs if str(job.get("job_id") or "") == clean_job_id]
        if clean_model:
            jobs = [job for job in jobs if str(job.get("model") or "") == clean_model]
        jobs.sort(
            key=lambda job: float(job.get("updated_ts") or job.get("created_ts") or 0),
            reverse=True,
        )
        visible = [self._public_prefetch_job(job) for job in jobs[:safe_limit]]
        return {
            "service": "norllama",
            "gateway": gateway_identity(),
            "time": now_iso(),
            "schema": "norllama.prefetch.jobs.v1",
            "count": len(visible),
            "items": visible,
        }

    def _update_prefetch_job(
        self, job_id: str, updates: dict[str, object]
    ) -> dict[str, object]:
        now = time.time()
        with self._lock:
            job = self._prefetch_jobs.get(job_id)
            if not job:
                return {}
            job.update(updates)
            job["updated_ts"] = now
            job["updated_at"] = now_iso()
            return dict(job)

    def _run_prefetch_job(
        self,
        *,
        job_id: str,
        base_url: str,
        upstream_path: str,
        request_body: bytes,
        timeout_s: float | None,
        priority: str,
    ) -> None:
        self._update_prefetch_job(
            job_id, {"status": "running", "started_at": now_iso()}
        )
        started = time.perf_counter()
        model = ""
        http_status = int(HTTPStatus.INTERNAL_SERVER_ERROR)
        content_length = 0
        content_type = "application/json"
        activity_extra: dict[str, object] = {}
        try:
            job = self._prefetch_jobs.get(job_id) or {}
            model = str(job.get("model") or "")
            http_status, response_headers, response_body = fetch_url(
                normalize_base_url(base_url) + upstream_path,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-Norllama-Priority": priority,
                },
                body=request_body,
                timeout_s=self.timeout_s if timeout_s is None else timeout_s,
            )
            content_length = len(response_body)
            content_type = response_headers.get("Content-Type", "application/json")
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            metrics = extract_ollama_metrics(response_body, content_type)
            response_doc = extract_jsonish_final_object(response_body) or {}
            ok = 200 <= int(http_status) < 300
            delegated_status = ""
            delegated_doc: dict[str, object] = {}
            if (
                upstream_path == "/v1/prefetch"
                and int(http_status) == HTTPStatus.ACCEPTED
            ):
                status_url = str(response_doc.get("status_url") or "").strip()
                if status_url:
                    poll_url = urllib.parse.urljoin(
                        normalize_base_url(base_url) + "/", status_url.lstrip("/")
                    )
                    poll_deadline = time.time() + max(
                        5.0, min(self.timeout_s, float(timeout_s or 30.0))
                    )
                    while time.time() < poll_deadline:
                        try:
                            poll_status, poll_headers, poll_body = fetch_url(
                                poll_url,
                                method="GET",
                                headers={"Accept": "application/json"},
                                timeout_s=min(5.0, self.timeout_s),
                            )
                            poll_doc = extract_jsonish_final_object(poll_body) or {}
                            items = (
                                poll_doc.get("items")
                                if isinstance(poll_doc.get("items"), list)
                                else []
                            )
                            item = (
                                items[0] if items and isinstance(items[0], dict) else {}
                            )
                            delegated_status = str(item.get("status") or "").strip()
                            delegated_doc = {
                                "http_status": poll_status,
                                "status": delegated_status,
                                "job_id": item.get("job_id"),
                                "request_duration_ms": item.get("request_duration_ms"),
                                "error": item.get("error"),
                            }
                            if delegated_status in {"warm", "failed"}:
                                break
                        except Exception as exc:
                            delegated_doc = {"error": str(exc)[:240]}
                        time.sleep(0.5)
                if delegated_status == "warm":
                    response_doc = {"delegated": response_doc, "peer": delegated_doc}
                    ok = True
                elif delegated_status == "failed":
                    response_doc = {"delegated": response_doc, "peer": delegated_doc}
                    ok = False
                else:
                    response_doc = {"delegated": response_doc, "peer": delegated_doc}
                    ok = True
            activity_extra = {
                "mode": "prefetch_job",
                "model": model,
                "prefetch_job_id": job_id,
                "prefetch_upstream": base_url,
                **metrics,
            }
            self._update_prefetch_job(
                job_id,
                {
                    "status": (
                        delegated_status
                        if delegated_status in {"warm", "failed"}
                        else "delegated"
                        if upstream_path == "/v1/prefetch"
                        and int(http_status) == HTTPStatus.ACCEPTED
                        else "warm"
                        if ok
                        else "failed"
                    ),
                    "ok": ok,
                    "http_status": int(http_status),
                    "completed_at": now_iso(),
                    "request_duration_ms": elapsed_ms,
                    "ollama_metrics": metrics,
                    "response": response_doc,
                    **(
                        {"error": ""}
                        if ok
                        else {
                            "error": str(
                                response_doc.get("error") or "prefetch_failed"
                            )[:240]
                        }
                    ),
                },
            )
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            activity_extra = {
                "mode": "prefetch_job",
                "model": model,
                "prefetch_job_id": job_id,
                "prefetch_upstream": base_url,
                "error": str(exc)[:240],
            }
            self._update_prefetch_job(
                job_id,
                {
                    "status": "failed",
                    "ok": False,
                    "http_status": int(HTTPStatus.BAD_GATEWAY),
                    "completed_at": now_iso(),
                    "request_duration_ms": elapsed_ms,
                    "error": str(exc)[:240],
                },
            )
            http_status = int(HTTPStatus.BAD_GATEWAY)
        self.record_activity(
            {
                "ts": now_iso(),
                "service": "norllama",
                "request_id": job_id,
                "client": "background",
                "method": "PREFETCH",
                "path": "/v1/prefetch",
                "status": int(http_status),
                "priority": priority,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "content_type": content_type,
                "content_length": int(content_length),
                "upstream": base_url,
                "attempts": [base_url],
                **activity_extra,
            }
        )

    def start_prefetch_job(
        self,
        *,
        kind: str,
        model: str,
        base_url: str,
        upstream_path: str,
        request_body: bytes,
        keep_alive: str,
        num_ctx: int | None,
        timeout_s: float | None,
        priority: str,
        request_id: str,
    ) -> tuple[dict[str, object], bool]:
        now = time.time()
        key = self._prefetch_job_key(
            kind=kind,
            base_url=base_url,
            model=model,
            keep_alive=keep_alive,
            num_ctx=num_ctx,
        )
        with self._lock:
            self._prune_prefetch_jobs_locked()
            existing_id = self._prefetch_job_keys.get(key)
            existing = self._prefetch_jobs.get(existing_id or "")
            if existing and str(existing.get("status") or "") in {"queued", "running"}:
                existing["duplicate_count"] = (
                    int(existing.get("duplicate_count") or 0) + 1
                )
                existing["updated_ts"] = now
                existing["updated_at"] = now_iso()
                return self._public_prefetch_job(dict(existing)), False
            if existing and str(existing.get("status") or "") == "warm":
                age = now - float(existing.get("updated_ts") or now)
                if age <= max(60.0, self.prefetch_job_ttl_s):
                    existing["duplicate_count"] = (
                        int(existing.get("duplicate_count") or 0) + 1
                    )
                    existing["updated_ts"] = now
                    existing["updated_at"] = now_iso()
                    return self._public_prefetch_job(dict(existing)), False
            job_id = request_id or uuid.uuid4().hex
            if job_id in self._prefetch_jobs:
                job_id = uuid.uuid4().hex
            job = {
                "job_id": job_id,
                "schema": "norllama.prefetch.job.v1",
                "key": key,
                "kind": kind,
                "status": "queued",
                "ok": True,
                "model": model,
                "keep_alive": keep_alive,
                "num_ctx": num_ctx,
                "priority": priority,
                "upstream": base_url,
                "upstream_path": upstream_path,
                "http_status": 0,
                "duplicate_count": 0,
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "created_ts": now,
                "updated_ts": now,
                "error": "",
            }
            self._prefetch_jobs[job_id] = job
            self._prefetch_job_keys[key] = job_id
        thread = threading.Thread(
            target=self._run_prefetch_job,
            kwargs={
                "job_id": job_id,
                "base_url": base_url,
                "upstream_path": upstream_path,
                "request_body": request_body,
                "timeout_s": timeout_s,
                "priority": priority,
            },
            name=f"norllama-prefetch-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return self._public_prefetch_job(job), True

    def render_ui_html(self) -> str:
        overview = self.overview()
        health = overview.get("health") or {}
        recent = overview.get("recent_activity") or {}
        routes = overview.get("routing") or {}
        fleet = overview.get("fleet") or []
        summary = overview.get("catalog_summary") or {}
        contract = overview.get("contract") or {}
        endpoints = overview.get("endpoints") or []
        highlights = overview.get("model_highlights") or []
        catalog = self.catalog()
        peer_ollama_counts: dict[str, int] = {}
        for item in catalog.get("models", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("provider") or "").strip() != "ollama":
                continue
            for host in item.get("hosts") or []:
                alias = self.host_alias(str(host or ""))
                if not alias:
                    continue
                peer_ollama_counts[alias] = peer_ollama_counts.get(alias, 0) + 1
        for row in fleet:
            label = str(row.get("label") or "")
            proxy_count = peer_ollama_counts.get(label, 0)
            ollama_info = row.get("ollama")
            if (
                proxy_count
                and isinstance(ollama_info, dict)
                and not ollama_info.get("healthy")
            ):
                ollama_info["proxy_model_count"] = proxy_count
                ollama_info["proxy_label"] = "via Norllama"
                selected = row.get("selected_lanes")
                if isinstance(selected, list) and "norllama" not in selected:
                    selected.append("norllama")
        chat_models = [
            row
            for row in catalog.get("models", [])
            if str(row.get("access") or "").startswith("unified_chat")
        ]
        chat_models.sort(
            key=lambda row: (
                0 if str(row.get("id") or "") == PREFERRED_UI_CHAT_MODEL else 1,
                str(row.get("id") or ""),
            )
        )

        def lane_state(row: dict[str, object], lane: str) -> str:
            if lane == "ollama":
                info = row.get("ollama") or {}
                if not info.get("healthy"):
                    proxy_count = int(info.get("proxy_model_count") or 0)
                    if proxy_count:
                        return f"via Norllama / {proxy_count} models"
                    return "down"
                loaded = info.get("loaded_models")
                loaded_text = "?" if loaded is None else str(loaded)
                return (
                    f"ok / {info.get('model_count', 0)} models / {loaded_text} loaded"
                )
            if lane == "media":
                info = row.get("media") or {}
                status = str(info.get("status") or "unknown")
                if status != "ok":
                    return status
                busy = "busy" if info.get("busy") else "idle"
                return f"{busy} / {info.get('free_mib', 0)} MiB free"
            if lane == "transcribe":
                info = row.get("transcribe") or {}
                status = str(info.get("status") or "unknown")
                model = str(info.get("model") or "")
                return status if not model else f"{status} / {model}"
            if lane == "image":
                info = row.get("image") or {}
                status = str(info.get("status") or "unknown")
                model = str(info.get("model") or "")
                return status if not model else f"{status} / {model}"
            info = row.get("ds4") or {}
            if not info.get("healthy"):
                return "-"
            return f"ok / {len(info.get('models') or [])} models"

        fleet_rows = "".join(
            "<tr>"
            f"<td><strong>{html.escape(str(row.get('label') or ''))}</strong><div class=\"subcell\">{html.escape(str(row.get('base_url') or ''))}</div></td>"
            f"<td>{html.escape(lane_state(row, 'ollama'))}</td>"
            f"<td>{html.escape(lane_state(row, 'media'))}</td>"
            f"<td>{html.escape(lane_state(row, 'transcribe'))}</td>"
            f"<td>{html.escape(lane_state(row, 'image'))}</td>"
            f"<td>{html.escape(lane_state(row, 'ds4'))}</td>"
            f"<td>{html.escape(', '.join(row.get('selected_lanes') or []) or '-')}</td>"
            "</tr>"
            for row in fleet
        )
        model_rows = []
        for row in catalog.get("models", []):
            replica_cell = html.escape(str(row.get("replica_count") or 0))
            host_cell = (
                html.escape(", ".join(row.get("hosts") or []))
                if self.expose_upstream_details
                else replica_cell
            )
            model_rows.append(
                "<tr>"
                f"<td>{html.escape(str(row.get('id') or ''))}</td>"
                f"<td>{html.escape(str(row.get('provider') or ''))}</td>"
                f"<td>{html.escape(', '.join(row.get('capabilities') or []))}</td>"
                f"<td>{html.escape(str(row.get('access') or ''))}</td>"
                f"<td>{host_cell}</td>"
                f"<td>{html.escape(str(row.get('recommended_path') or ''))}</td>"
                f"<td>{html.escape(str(row.get('summary') or ''))}</td>"
                "</tr>"
            )
        option_rows: list[str] = []
        for row in chat_models:
            model_id = str(row.get("id") or "")
            selected = " selected" if model_id == PREFERRED_UI_CHAT_MODEL else ""
            option_rows.append(
                f'<option value="{html.escape(model_id)}"{selected}>{html.escape(model_id)}</option>'
            )
        options = "\n".join(option_rows)
        features = "".join(
            f"<li><strong>{html.escape(str(key))}</strong>: {html.escape(json.dumps(value))}</li>"
            for key, value in catalog.get("features", {}).items()
        )
        endpoint_rows = "".join(
            "<tr>"
            f"<td><code>{html.escape(str(item.get('path') or ''))}</code></td>"
            f"<td>{html.escape(', '.join(item.get('methods') or []))}</td>"
            f"<td>{html.escape(str(item.get('kind') or ''))}</td>"
            "</tr>"
            for item in endpoints
        )
        highlight_rows = "".join(
            "<tr>"
            f"<td>{html.escape(str(row.get('id') or ''))}</td>"
            f"<td>{html.escape(str(row.get('provider') or ''))}</td>"
            f"<td>{html.escape(str(row.get('summary') or ''))}</td>"
            "</tr>"
            for row in highlights
        )
        activity_rows = "".join(
            "<tr>"
            f"<td>{html.escape(str(item.get('ts') or ''))}</td>"
            f"<td>{html.escape(str(item.get('method') or ''))}</td>"
            f"<td>{html.escape(str(item.get('path') or ''))}</td>"
            f"<td>{html.escape(str(item.get('status') or ''))}</td>"
            f"<td>{html.escape(str(item.get('priority') or ''))}</td>"
            + (
                f"<td>{html.escape(str(item.get('upstream') or ''))}</td>"
                if self.expose_upstream_details
                else ""
            )
            + f"<td>{html.escape(str(item.get('duration_ms') or ''))}</td>"
            "</tr>"
            for item in recent.get("items", [])
        )
        route_cards = (
            f"""
    <div class="grid">
      <div class="card"><div class="k">Ollama Route</div><div class="v mono">{html.escape(str(routes.get('ollama') or ''))}</div></div>
      <div class="card"><div class="k">DS4 Route</div><div class="v mono">{html.escape(str(routes.get('ds4') or ''))}</div></div>
      <div class="card"><div class="k">Media Route</div><div class="v mono">{html.escape(str(routes.get('media') or ''))}</div></div>
      <div class="card"><div class="k">Transcribe Route</div><div class="v mono">{html.escape(str(routes.get('transcribe') or ''))}</div></div>
      <div class="card"><div class="k">Image Route</div><div class="v mono">{html.escape(str(routes.get('image') or ''))}</div></div>
    </div>
"""
            if self.expose_upstream_details
            else """
    <div class="grid">
      <div class="card"><div class="k">Gateway Scope</div><div class="v">Norllama-only discovery</div></div>
      <div class="card"><div class="k">Policy</div><div class="v">Downstream Spark and Mini services stay hidden behind the gateway.</div></div>
    </div>
"""
        )
        fleet_section = (
            f"""
    <div style="margin-top:18px;">
      <h2>Fleet Matrix</h2>
      <div class="sub">What each Spark is carrying right now, and which lanes Norllama is actively selecting.</div>
      <table>
        <thead>
          <tr><th>Host</th><th>Ollama</th><th>Media</th><th>ASR</th><th>Images</th><th>DS4</th><th>Selected Lanes</th></tr>
        </thead>
        <tbody>
          {fleet_rows}
        </tbody>
      </table>
    </div>
"""
            if self.expose_upstream_details
            else """
    <div style="margin-top:18px;">
      <h2>Gateway Boundary</h2>
      <div class="sub">Norllama intentionally hides downstream Spark and Mini topology. Clients should target gateway routes only.</div>
    </div>
"""
        )
        activity_header = (
            "<tr><th>Time</th><th>Method</th><th>Path</th><th>Status</th><th>Priority</th><th>Upstream</th><th>ms</th></tr>"
            if self.expose_upstream_details
            else "<tr><th>Time</th><th>Method</th><th>Path</th><th>Status</th><th>Priority</th><th>ms</th></tr>"
        )
        host_header = "Hosts" if self.expose_upstream_details else "Replicas"
        hero_sub = (
            "Unified Spark front layer for Ollama, DS4, media, and ASR."
            if self.advertise_aux_services or self.expose_upstream_details
            else "Unified Norllama front layer for local model access."
        )
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Norllama</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0b1017;
      --paper: #121a24;
      --ink: #edf4f8;
      --muted: #95a8bb;
      --line: #273545;
      --accent: #5bd3c7;
      --accent2: #f6b15f;
      --ink2: #c8f2f5;
      --field: #0f1620;
      --table-head: #172232;
      --code-bg: #070b10;
      --chip-bg: #182433;
      --shadow: rgba(0,0,0,0.38);
    }}
    body {{ margin: 0; font-family: "Iowan Old Style", "Palatino Linotype", serif; background: radial-gradient(circle at top, #172033, var(--bg)); color: var(--ink); }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
    h1, h2 {{ margin: 0 0 12px; }}
    .sub {{ color: var(--muted); margin-bottom: 18px; }}
    .grid {{ display: grid; gap: 14px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); margin-bottom: 18px; }}
    .card {{ background: var(--paper); border: 1px solid var(--line); border-radius: 12px; padding: 16px; box-shadow: 0 16px 42px var(--shadow); }}
    .hero {{ display:grid; gap:14px; grid-template-columns: 1.3fr 1fr; margin-bottom:18px; }}
    .hero-card {{ background: linear-gradient(135deg, #142235, #121a24); }}
    .k {{ color: var(--muted); font-size: 0.88rem; text-transform: uppercase; letter-spacing: 0.08em; }}
    .v {{ font-size: 1rem; font-weight: 700; word-break: break-word; }}
    .mono {{ font-family: "SFMono-Regular", "Menlo", "Consolas", monospace; }}
    .two {{ display: grid; gap: 18px; grid-template-columns: 1.05fr 1.4fr; }}
    textarea, select, button, input {{ width: 100%; font: inherit; }}
    textarea, select, input {{ box-sizing: border-box; border: 1px solid var(--line); border-radius: 10px; padding: 10px; background: var(--field); color: var(--ink); }}
    button {{ border: 0; background: linear-gradient(135deg, #118277, #1a6285); color: #f7fffe; padding: 12px 14px; border-radius: 999px; cursor: pointer; font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--paper); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ background: var(--table-head); font-size: 0.9rem; }}
    pre {{ white-space: pre-wrap; background: var(--code-bg); color: #d9f4ef; padding: 14px; border-radius: 12px; min-height: 160px; }}
    ul {{ margin: 8px 0 0 18px; }}
    .chips {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }}
    .chip {{ display:inline-block; padding:6px 10px; border-radius:999px; background:var(--chip-bg); border:1px solid var(--line); font-size:0.88rem; color:var(--ink2); }}
    .subcell {{ color: var(--muted); font-size: 0.86rem; margin-top: 4px; }}
    .code-links a {{ color: var(--accent); text-decoration: none; }}
    .code-links a:hover {{ text-decoration: underline; }}
    .form-grid {{ display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:10px; margin-top:10px; }}
    .check-row {{ display:flex; align-items:center; gap:10px; margin-top:12px; color:var(--ink2); }}
    .check-row input {{ width:auto; }}
    .image-preview {{ display:grid; place-items:center; min-height:260px; margin-top:12px; border:1px solid var(--line); border-radius:12px; background:var(--code-bg); overflow:hidden; }}
    .image-preview img {{ max-width:100%; height:auto; display:block; }}
    @media (max-width: 900px) {{ .hero, .two {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 700px) {{ .form-grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="card hero-card">
        <h1>Norllama</h1>
        <div class="sub">{html.escape(hero_sub)}</div>
        <div class="chips">
          <span class="chip">status: {html.escape(str(overview.get('status') or 'unknown'))}</span>
          <span class="chip">async: {html.escape(str(contract.get('async_mode') or 'unknown'))}</span>
          <span class="chip">priority: {html.escape(str(contract.get('priority_mode') or 'unknown'))}</span>
          <span class="chip">structured logs: {html.escape(str(contract.get('structured_logging') or False).lower())}</span>
          <span class="chip">request ids: {html.escape(str(contract.get('request_ids') or False).lower())}</span>
          <span class="chip">head paths: {html.escape(str(contract.get('head_support_count') or 0))}</span>
        </div>
      </div>
      <div class="card">
        <h2>Quick Links</h2>
        <div class="sub">Use the overview doc for bots, and this page for humans.</div>
        <div class="code-links">
          <div><a href="/v1/overview"><code>/v1/overview</code></a></div>
          <div><a href="/v1/capabilities"><code>/v1/capabilities</code></a></div>
          <div><a href="/v1/catalog"><code>/v1/catalog</code></a></div>
          <div><a href="/v1/activity"><code>/v1/activity</code></a></div>
          <div><a href="/v1/prefetch/status"><code>/v1/prefetch/status</code></a></div>
          <div><a href="/health"><code>/health</code></a></div>
        </div>
      </div>
    </div>
    <div class="grid">
      <div class="card"><div class="k">Visible Models</div><div class="v">{html.escape(str(summary.get('visible_model_count') or 0))}</div></div>
      <div class="card"><div class="k">Unified Chat Models</div><div class="v">{html.escape(str(summary.get('chat_models') or 0))}</div></div>
      <div class="card"><div class="k">Specialized Models</div><div class="v">{html.escape(str(summary.get('specialized_models') or 0))}</div></div>
      <div class="card"><div class="k">Hidden Catalog Rows</div><div class="v">{html.escape(str(summary.get('hidden_model_count') or 0))}</div></div>
      <div class="card"><div class="k">Recent Requests</div><div class="v">{html.escape(str(recent.get('count') or 0))}</div></div>
      <div class="card"><div class="k">Rendered At</div><div class="v mono">{html.escape(str(overview.get('time') or ''))}</div></div>
    </div>
    {route_cards}
    {fleet_section}
    <div class="two">
      <div class="card">
        <h2>Playground</h2>
        <div class="sub">Simple human test surface for unified chat lanes.</div>
        <label class="k" for="model">Model</label>
        <select id="model">{options}</select>
        <label class="k" for="priority" style="display:block;margin-top:10px;">Priority Hint</label>
        <select id="priority">
          <option value="normal">normal</option>
          <option value="high">high</option>
          <option value="background">background</option>
        </select>
        <label class="k" for="prompt" style="display:block;margin-top:10px;">Prompt</label>
        <textarea id="prompt" rows="8">Reply with exactly OK.</textarea>
        <div style="margin-top:12px;"><button id="send">Send</button></div>
        <pre id="out">No request yet.</pre>
      </div>
      <div class="card">
        <h2>Bot Contract</h2>
        <div class="sub">Machine-facing behavior that matters for agents and wrappers.</div>
        <ul>{features}</ul>
        <div class="sub" style="margin-top:12px;">Use <code>/v1/overview</code> for a compact gateway snapshot, then <code>/v1/capabilities</code>, <code>/v1/catalog</code>, and <code>/v1/activity</code> for deeper bot-to-bot discovery and tracing.</div>
      </div>
    </div>
    <div class="two" style="margin-top:18px;">
      <div class="card">
        <h2>Image Shell</h2>
        <div class="sub">Local Stable Diffusion-compatible lane through Norllama.</div>
        <label class="k" for="imagePrompt">Prompt</label>
        <textarea id="imagePrompt" rows="5">a small matte black shell terminal on a desk, clean product render</textarea>
        <label class="k" for="imageNegative" style="display:block;margin-top:10px;">Negative Prompt</label>
        <textarea id="imageNegative" rows="2">blurry, distorted text, watermark</textarea>
        <div class="form-grid">
          <div>
            <label class="k" for="imageSize">Size</label>
            <select id="imageSize">
              <option value="768x768">768x768</option>
              <option value="1024x1024" selected>1024x1024</option>
              <option value="1024x768">1024x768</option>
              <option value="768x1024">768x1024</option>
            </select>
          </div>
          <div>
            <label class="k" for="imageSteps">Steps</label>
            <input id="imageSteps" type="number" min="1" max="150" value="24">
          </div>
          <div>
            <label class="k" for="imageCount">Count</label>
            <input id="imageCount" type="number" min="1" max="4" value="1">
          </div>
        </div>
        <label class="check-row" for="imageAdult">
          <input id="imageAdult" type="checkbox">
          <span>Adult Mode</span>
        </label>
        <div style="margin-top:12px;"><button id="generateImage">Generate</button></div>
      </div>
      <div class="card">
        <h2>Image Output</h2>
        <div class="sub">The response is logged as <code>image_generate</code> with worker attribution and offline-local accounting.</div>
        <pre id="imageOut">No image request yet.</pre>
        <div id="imagePreview" class="image-preview"><span class="sub">No preview.</span></div>
      </div>
    </div>
    <div style="margin-top:18px;">
      <h2>API Surface</h2>
      <div class="sub">Human summary of what Norllama exposes without reading the raw capability doc.</div>
      <table>
        <thead>
          <tr><th>Path</th><th>Methods</th><th>Kind</th></tr>
        </thead>
        <tbody>
          {endpoint_rows}
        </tbody>
      </table>
    </div>
    <div style="margin-top:18px;">
      <h2>Recent Activity</h2>
      <div class="sub">Latest gateway work, including status, priority hint, and latency.</div>
      <table id="activity-table">
        <thead>
          {activity_header}
        </thead>
        <tbody>
          {activity_rows}
        </tbody>
      </table>
    </div>
    <div style="margin-top:18px;">
      <h2>Highlighted Chat Lanes</h2>
      <div class="sub">High-signal models exposed through unified chat right now.</div>
      <table>
        <thead>
          <tr><th>Model</th><th>Provider</th><th>Brief</th></tr>
        </thead>
        <tbody>
          {highlight_rows}
        </tbody>
      </table>
    </div>
    <div style="margin-top:18px;">
      <h2>Model Catalog</h2>
      <table>
        <thead>
          <tr><th>Model</th><th>Provider</th><th>Capabilities</th><th>Access</th><th>{html.escape(host_header)}</th><th>Recommended Path</th><th>Brief</th></tr>
        </thead>
        <tbody>
          {''.join(model_rows)}
        </tbody>
      </table>
    </div>
  </div>
  <script>
    const out = document.getElementById('out');
    document.getElementById('send').addEventListener('click', async () => {{
      const model = document.getElementById('model').value;
      const priority = document.getElementById('priority').value;
      const prompt = document.getElementById('prompt').value;
      out.textContent = 'Working...';
      try {{
        const resp = await fetch('/v1/chat/completions', {{
          method: 'POST',
          headers: {{
            'Content-Type': 'application/json',
            'X-Norllama-Priority': priority,
          }},
          body: JSON.stringify({{
            model,
            stream: false,
            messages: [{{ role: 'user', content: prompt }}]
          }})
        }});
        const text = await resp.text();
        out.textContent = [
          'status=' + resp.status,
          'request_id=' + (resp.headers.get('X-Norllama-Request-Id') || ''),
          'priority=' + (resp.headers.get('X-Norllama-Priority-Applied') || ''),
          {("'upstream=' + (resp.headers.get('X-Norllama-Upstream') || '')," if self.expose_upstream_details else "")}
          text
        ].join('\\n');
      }} catch (err) {{
        out.textContent = String(err);
      }}
    }});
    const imageOut = document.getElementById('imageOut');
    const imagePreview = document.getElementById('imagePreview');
    document.getElementById('generateImage').addEventListener('click', async () => {{
      const prompt = document.getElementById('imagePrompt').value;
      const negative_prompt = document.getElementById('imageNegative').value;
      const size = document.getElementById('imageSize').value;
      const steps = Number(document.getElementById('imageSteps').value || 24);
      const n = Number(document.getElementById('imageCount').value || 1);
      const allow_nsfw = document.getElementById('imageAdult').checked;
      const content_rating = allow_nsfw ? 'adult' : 'standard';
      imageOut.textContent = 'Working...';
      imagePreview.innerHTML = '<span class="sub">Generating...</span>';
      try {{
        const resp = await fetch('/v1/images/generations', {{
          method: 'POST',
          headers: {{
            'Content-Type': 'application/json',
            'X-Norllama-Priority': 'background',
          }},
          body: JSON.stringify({{ prompt, negative_prompt, size, steps, n, allow_nsfw, content_rating }})
        }});
        const text = await resp.text();
        let doc = null;
        try {{ doc = JSON.parse(text); }} catch (err) {{}}
        imageOut.textContent = [
          'status=' + resp.status,
          'request_id=' + (resp.headers.get('X-Norllama-Request-Id') || ''),
          {("'upstream=' + (resp.headers.get('X-Norllama-Upstream') || '')," if self.expose_upstream_details else "")}
          text
        ].join('\\n');
        const first = doc && doc.data && doc.data[0] ? doc.data[0] : null;
        const b64 = first && first.b64_json ? first.b64_json : '';
        const url = first && first.url ? first.url : '';
        if (b64) {{
          const src = b64.startsWith('data:') ? b64 : 'data:image/png;base64,' + b64;
          imagePreview.innerHTML = '<img alt="Generated image" src="' + src + '">';
        }} else if (url) {{
          imagePreview.innerHTML = '<img alt="Generated image" src="' + url + '">';
        }} else {{
          imagePreview.innerHTML = '<span class="sub">No image returned.</span>';
        }}
      }} catch (err) {{
        imageOut.textContent = String(err);
        imagePreview.innerHTML = '<span class="sub">Request failed.</span>';
      }}
    }});
    async function refreshActivity() {{
      try {{
        const resp = await fetch('/v1/activity?limit=12');
        const doc = await resp.json();
        const body = document.querySelector('#activity-table tbody');
        body.innerHTML = (doc.items || []).map((item) => {{
          return '<tr>' +
            '<td>' + (item.ts || '') + '</td>' +
            '<td>' + (item.method || '') + '</td>' +
            '<td>' + (item.path || '') + '</td>' +
            '<td>' + String(item.status || '') + '</td>' +
            '<td>' + (item.priority || '') + '</td>' +
            {("'<td>' + (item.upstream || '') + '</td>' +" if self.expose_upstream_details else "")}
            '<td>' + String(item.duration_ms || '') + '</td>' +
          '</tr>';
        }}).join('');
      }} catch (err) {{
      }}
    }}
    setInterval(refreshActivity, 4000);
  </script>
</body>
</html>"""

    def health(self) -> dict:
        media_selected, media_rows = self.choose_media_base()
        asr_selected, asr_rows = self.choose_transcribe_base()
        ocr_selected, ocr_rows = self.choose_ocr_base()
        rerank_selected, rerank_rows = self.choose_rerank_base()
        safety_selected, safety_rows = self.choose_safety_base()
        image_selected, image_rows = self.choose_image_base()
        ollama_selected, ollama_rows = self.choose_ollama_base()
        ds4_selected, ds4_rows = self.choose_ds4_base()
        local_visible_model_count = 0
        for row in ollama_rows:
            local_visible_model_count += len(row.get("model_docs") or [])
        if isinstance(ds4_rows, list):
            for row in ds4_rows:
                local_visible_model_count += len(row.get("model_docs") or [])
        local_visible_model_count += len(
            [row for row in ocr_rows if row.get("status") == "ok"]
        )
        local_visible_model_count += len(
            [row for row in rerank_rows if row.get("status") == "ok"]
        )
        local_visible_model_count += len(
            [row for row in safety_rows if row.get("status") == "ok"]
        )
        local_visible_model_count += len(
            [row for row in image_rows if row.get("status") == "ok"]
        )
        payload = {
            "service": "norllama",
            "gateway": gateway_identity(),
            "status": "ok",
            "time": now_iso(),
            "catalog": {
                "hidden_model_ids": sorted(HIDDEN_MODEL_IDS),
                "visible_model_count": local_visible_model_count,
                "scope": "local_downstreams_only",
            },
            "features": self.feature_flags(),
        }
        if self.expose_upstream_details:
            payload["routing"] = {
                "ollama": ollama_selected,
                "ds4": ds4_selected,
                "media": media_selected,
                "transcribe": asr_selected,
                "ocr": ocr_selected,
                "rerank": rerank_selected,
                "safety": safety_selected,
                "image": image_selected,
            }
            payload["downstreams"] = {
                "media": media_rows,
                "transcribe": asr_rows,
                "ocr": ocr_rows,
                "rerank": rerank_rows,
                "safety": safety_rows,
                "image": image_rows,
                "ollama": ollama_rows,
                "ds4": ds4_rows,
            }
        else:
            payload["gateway"]["public_provider"] = self.public_provider_name
            payload["gateway"]["managed_lanes"] = {
                "chat": True,
                "prefetch": True,
                "evict": True,
                "safety": True,
                "image_generation": True,
                "aux_services_advertised": self.advertise_aux_services,
                "peer_frontdoor_fallback": bool(self.peer_bases),
                "peer_frontdoor_count": len(self.peer_bases),
            }
        return payload

    def healthz(self) -> dict:
        return {
            "service": "norllama",
            "gateway": gateway_identity(),
            "status": "ok",
            "time": now_iso(),
            "features": self.feature_flags(),
        }


class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Norllama/0.1"

    @property
    def app(self) -> App:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:
        sys.stdout.write(
            "%s - - [%s] %s\n"
            % (self.address_string(), self.log_date_time_string(), fmt % args)
        )
        sys.stdout.flush()

    def begin_request(self) -> None:
        priority = self.headers.get("X-Norllama-Priority", "").strip().lower()
        if priority not in PRIORITY_LEVELS:
            priority = "normal"
        try:
            peer_hop = int(self.headers.get("X-Norllama-Peer-Hop", "0").strip() or "0")
        except Exception:
            peer_hop = 0
        if peer_hop < 0:
            peer_hop = 0
        self._request_id = (
            self.headers.get("X-Request-Id", "").strip() or uuid.uuid4().hex
        )
        self._priority = priority
        self._peer_hop = peer_hop
        self._started_at = time.perf_counter()
        self._log_sent = False
        self._model_hint = ""
        self._activity_extra = {}

    def peer_candidate_bases(
        self, model_id: str | None = None
    ) -> tuple[list[str], list[dict]]:
        if int(getattr(self, "_peer_hop", 0)) >= self.app.max_peer_hops:
            return [], self.app.peer_frontdoor_rows()
        return self.app.peer_candidate_bases(model_id)

    def peer_forward_headers(
        self, headers: dict[str, str] | None = None
    ) -> dict[str, str]:
        outgoing = dict(headers or {})
        outgoing["X-Norllama-Peer-Hop"] = str(int(getattr(self, "_peer_hop", 0)) + 1)
        via = self.headers.get("X-Norllama-Via", "").strip()
        marker = self.app.self_base_urls[0] if self.app.self_base_urls else ""
        chain = [item for item in via.split(",") if item.strip()]
        if marker:
            chain.append(marker)
        if chain:
            outgoing["X-Norllama-Via"] = ",".join(unique_preserve(chain))
        return outgoing

    def emit_request_log(
        self,
        *,
        status: int,
        content_length: int,
        content_type: str,
        upstream: str = "",
        attempts: str = "",
    ) -> None:
        if getattr(self, "_log_sent", False):
            return
        duration_ms = round(
            (time.perf_counter() - getattr(self, "_started_at", time.perf_counter()))
            * 1000,
            3,
        )
        record = {
            "ts": now_iso(),
            "service": "norllama",
            "request_id": getattr(self, "_request_id", ""),
            "client": self.client_address[0] if self.client_address else "",
            "method": self.command,
            "path": self.path,
            "status": int(status),
            "priority": getattr(self, "_priority", "normal"),
            "duration_ms": duration_ms,
            "content_type": content_type,
            "content_length": int(content_length),
            "upstream": upstream,
            "attempts": attempts.split(",") if attempts else [],
        }
        model_hint = str(getattr(self, "_model_hint", "") or "").strip()
        if model_hint:
            record["model"] = model_hint
        if isinstance(getattr(self, "_activity_extra", None), dict):
            record.update(getattr(self, "_activity_extra"))
        self.app.record_activity(record)
        sys.stdout.write(json.dumps(record, sort_keys=True) + "\n")
        sys.stdout.flush()
        self._log_sent = True

    def send_json(
        self, status: int, payload: dict, *, extra_headers: dict[str, str] | None = None
    ) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        upstream = ""
        attempts = ""
        if extra_headers:
            upstream = str(extra_headers.get("X-Norllama-Upstream") or "")
            attempts = str(extra_headers.get("X-Norllama-Attempts") or "")
        norllama_meta = payload.get("norllama") if isinstance(payload, dict) else {}
        if isinstance(norllama_meta, dict):
            activity_extra = dict(getattr(self, "_activity_extra", {}) or {})
            for key in (
                "capability",
                "score_method",
                "upstream",
                "selected_provider",
                "selected_model",
                "selected_worker",
                "frontdoor",
                "peer_path",
                "usage_bucket",
                "cloud_proxy",
                "fallback_used",
                "fallback_reason",
                "output_shape",
                "verifier_result",
                "native_rerank_error",
                "native_safety_error",
                "image_count",
                "allow_nsfw",
                "content_rating",
                "safety_profile",
            ):
                value = norllama_meta.get(key)
                if value is not None and value != "":
                    activity_extra[key] = value
            if isinstance(norllama_meta.get("attempts"), list):
                activity_extra["attempts"] = [
                    str(item) for item in norllama_meta.get("attempts") if str(item)
                ]
            if isinstance(norllama_meta.get("native_rerank_attempts"), list):
                activity_extra["native_rerank_attempts"] = [
                    str(item)
                    for item in norllama_meta.get("native_rerank_attempts")
                    if str(item)
                ]
            if isinstance(payload, dict):
                embedding_model = str(payload.get("embedding_model") or "").strip()
                if embedding_model:
                    activity_extra["embedding_model"] = embedding_model
            self._activity_extra = activity_extra
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Norllama-Request-Id", getattr(self, "_request_id", ""))
        self.send_header(
            "X-Norllama-Priority-Applied", getattr(self, "_priority", "normal")
        )
        for key, value in (extra_headers or {}).items():
            if key.lower() not in {"content-length", "content-type"}:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.emit_request_log(
            status=status,
            content_length=len(body),
            content_type="application/json",
            upstream=upstream,
            attempts=attempts,
        )

    def send_html(self, status: int, body_text: str) -> None:
        body = body_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Norllama-Request-Id", getattr(self, "_request_id", ""))
        self.send_header(
            "X-Norllama-Priority-Applied", getattr(self, "_priority", "normal")
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.emit_request_log(
            status=status, content_length=len(body), content_type="text/html"
        )

    def send_upstream(
        self,
        status: int,
        headers: dict[str, str],
        body: bytes,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        for key, value in headers.items():
            lower_key = key.lower()
            if (
                lower_key in HOP_HEADERS
                or lower_key in {"server", "date"}
                or lower_key.startswith("x-norllama-")
            ):
                continue
            self.send_header(key, value)
        self.send_header("X-Norllama-Request-Id", getattr(self, "_request_id", ""))
        self.send_header(
            "X-Norllama-Priority-Applied", getattr(self, "_priority", "normal")
        )
        if self.app.expose_upstream_details:
            worker_endpoint = ""
            if extra_headers:
                upstream = extra_headers.get("X-Norllama-Upstream", "")
                normalized_upstream = normalize_base_url(upstream) if upstream else ""
                if normalized_upstream and normalized_upstream in set(
                    self.app.peer_bases
                ):
                    worker_endpoint = normalized_upstream
            if not worker_endpoint:
                worker_endpoint = (
                    self.app.self_base_urls[0] if self.app.self_base_urls else ""
                )
            if worker_endpoint:
                self.send_header("X-Norllama-Worker-Endpoint", worker_endpoint)
        if extra_headers:
            for key, value in extra_headers.items():
                if not self.app.expose_upstream_details and key in {
                    "X-Norllama-Upstream",
                    "X-Norllama-Attempts",
                }:
                    continue
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        upstream = ""
        attempts = ""
        if extra_headers:
            upstream = extra_headers.get("X-Norllama-Upstream", "")
            attempts = extra_headers.get("X-Norllama-Attempts", "")
        content_type = headers.get("Content-Type", "application/octet-stream")
        metrics = extract_ollama_metrics(body, content_type)
        if metrics:
            activity_extra = dict(getattr(self, "_activity_extra", {}) or {})
            activity_extra.update(metrics)
            self._activity_extra = activity_extra
        self.emit_request_log(
            status=status,
            content_length=len(body),
            content_type=content_type,
            upstream=upstream,
            attempts=attempts,
        )

    def send_head_only(
        self, status: int, *, content_type: str, content_length: int
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Norllama-Request-Id", getattr(self, "_request_id", ""))
        self.send_header(
            "X-Norllama-Priority-Applied", getattr(self, "_priority", "normal")
        )
        self.send_header("Content-Length", str(content_length))
        self.end_headers()
        self.emit_request_log(
            status=status, content_length=content_length, content_type=content_type
        )

    def send_empty(
        self, status: int, *, extra_headers: dict[str, str] | None = None
    ) -> None:
        self.send_response(status)
        self.send_header("X-Norllama-Request-Id", getattr(self, "_request_id", ""))
        self.send_header(
            "X-Norllama-Priority-Applied", getattr(self, "_priority", "normal")
        )
        self.send_header("Content-Length", "0")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.emit_request_log(status=status, content_length=0, content_type="")

    def read_body(self) -> bytes:
        raw_length = self.headers.get("Content-Length", "0").strip()
        try:
            content_length = int(raw_length)
        except Exception:
            content_length = 0
        if content_length <= 0:
            return b""
        return self.rfile.read(content_length)

    def forward(
        self,
        base_url: str,
        upstream_path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        method: str | None = None,
    ) -> None:
        status, response_headers, response_body = self.request_upstream(
            base_url, upstream_path, headers=headers, body=body, method=method
        )
        self.send_upstream(
            status,
            response_headers,
            response_body,
            extra_headers={"X-Norllama-Upstream": base_url},
        )

    def forward_candidates(
        self,
        bases: list[str],
        upstream_path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        method: str | None = None,
        peer_bases: set[str] | None = None,
    ) -> None:
        attempted: list[str] = []
        last: tuple[int, dict[str, str], bytes] | None = None
        last_base = ""
        for base in bases:
            attempted.append(base)
            try:
                request_headers = dict(headers or {})
                if peer_bases and normalize_base_url(base) in peer_bases:
                    request_headers = self.peer_forward_headers(request_headers)
                result = self.request_upstream(
                    base,
                    upstream_path,
                    headers=request_headers or None,
                    body=body,
                    method=method,
                )
            except Exception as exc:
                last = (
                    int(HTTPStatus.BAD_GATEWAY),
                    {"Content-Type": "application/json; charset=utf-8"},
                    json.dumps(
                        {
                            "ok": False,
                            "error": "upstream_unavailable",
                            "detail": str(exc),
                        }
                    ).encode("utf-8"),
                )
                last_base = base
                continue
            last = result
            last_base = base
            if result[0] == 503 or result[0] >= 500:
                continue
            self.send_upstream(
                result[0],
                result[1],
                result[2],
                extra_headers={
                    "X-Norllama-Upstream": base,
                    "X-Norllama-Attempts": ",".join(attempted),
                },
            )
            return
        if last is None:
            self.send_json(
                HTTPStatus.BAD_GATEWAY, {"ok": False, "error": "no_upstream_candidates"}
            )
            return
        self.send_upstream(
            last[0],
            last[1],
            last[2],
            extra_headers={
                "X-Norllama-Upstream": last_base,
                "X-Norllama-Attempts": ",".join(attempted),
            },
        )

    def request_upstream(
        self,
        base_url: str,
        upstream_path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        method: str | None = None,
        timeout_s: float | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        outgoing_headers: dict[str, str] = {}
        for key, value in self.headers.items():
            if key.lower() in HOP_HEADERS or key.lower() == "authorization":
                continue
            outgoing_headers[key] = value
        if headers:
            outgoing_headers.update(headers)
        return fetch_url(
            base_url.rstrip("/") + upstream_path,
            method=method or self.command,
            headers=outgoing_headers,
            body=body,
            timeout_s=self.app.timeout_s if timeout_s is None else timeout_s,
        )

    def extract_ollama_model(self, body: bytes) -> str | None:
        content_type = (
            self.headers.get("Content-Type", "").strip() or "application/json"
        )
        if "json" not in content_type.lower() or not body:
            return None
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return None
        for key in ("model", "name"):
            raw_value = payload.get(key)
            if raw_value is None:
                continue
            value = str(raw_value).strip()
            if value:
                return value
        return None

    def parse_json_body(self, body: bytes) -> dict[str, object] | None:
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception as exc:
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "invalid_json", "detail": str(exc)},
            )
            return None
        if not isinstance(payload, dict):
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "ok": False,
                    "error": "invalid_json",
                    "detail": "request body must be a JSON object",
                },
            )
            return None
        return payload

    def clamp_image_int(
        self, value: object, default: int, *, minimum: int, maximum: int
    ) -> int:
        try:
            parsed = int(value) if value is not None and value != "" else default
        except Exception:
            parsed = default
        return max(minimum, min(parsed, maximum))

    def image_size_from_payload(self, payload: dict[str, object]) -> tuple[int, int]:
        raw = payload.get("size") or payload.get("resolution")
        width = payload.get("width")
        height = payload.get("height")
        if isinstance(raw, str):
            clean = raw.lower().replace("*", "x").replace(" ", "")
            if "x" in clean:
                width, height = clean.split("x", 1)
        elif isinstance(raw, dict):
            width = raw.get("width") or raw.get("w") or width
            height = raw.get("height") or raw.get("h") or height
        return (
            self.clamp_image_int(width, 1024, minimum=64, maximum=2048),
            self.clamp_image_int(height, 1024, minimum=64, maximum=2048),
        )

    def image_timeout_from_payload(self, payload: dict[str, object]) -> float:
        raw = payload.get("timeout_seconds") or payload.get("timeout")
        try:
            timeout_s = float(raw) if raw not in (None, "") else self.app.timeout_s
        except Exception:
            timeout_s = self.app.timeout_s
        return max(5.0, min(timeout_s, 900.0))

    def truthy_payload_value(self, value: object) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
            "adult",
            "nsfw",
        }

    def image_allow_nsfw(self, payload: dict[str, object]) -> bool:
        rating = (
            str(payload.get("content_rating") or payload.get("rating") or "")
            .strip()
            .lower()
        )
        return (
            self.truthy_payload_value(payload.get("allow_nsfw"))
            or self.truthy_payload_value(payload.get("nsfw"))
            or self.truthy_payload_value(payload.get("adult"))
            or rating in {"adult", "explicit", "nsfw", "r", "x"}
        )

    def image_content_rating(self, payload: dict[str, object]) -> str:
        raw = str(payload.get("content_rating") or payload.get("rating") or "").strip()
        clean = raw.lower().replace("_", "-")
        if clean in {"adult", "nsfw", "explicit", "r", "x"}:
            return "adult"
        if clean in {"mature", "suggestive"}:
            return "mature"
        if self.image_allow_nsfw(payload):
            return "adult"
        return "standard"

    def image_safety_profile(
        self, payload: dict[str, object], *, content_rating: str
    ) -> str:
        raw = str(payload.get("safety_profile") or "").strip().lower()
        if raw:
            return raw
        return "adult_opt_in" if content_rating == "adult" else "standard"

    def prompt_from_payload(self, payload: dict[str, object]) -> str:
        prompt = str(payload.get("prompt") or payload.get("input") or "").strip()
        if prompt:
            return prompt
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return ""
        parts: list[str] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                parts.append(content.strip())
        return "\n".join(parts).strip()

    def stable_diffusion_payload(
        self, payload: dict[str, object], *, prompt: str, model: str
    ) -> dict[str, object]:
        width, height = self.image_size_from_payload(payload)
        request_payload: dict[str, object] = {
            "prompt": prompt,
            "negative_prompt": str(payload.get("negative_prompt") or "").strip(),
            "batch_size": self.clamp_image_int(
                payload.get("n", payload.get("count")), 1, minimum=1, maximum=4
            ),
            "width": width,
            "height": height,
            "steps": self.clamp_image_int(
                payload.get("steps"), 24, minimum=1, maximum=150
            ),
        }
        if payload.get("cfg_scale") not in (None, ""):
            try:
                request_payload["cfg_scale"] = max(
                    1.0, min(float(payload.get("cfg_scale")), 30.0)
                )
            except Exception:
                pass
        if payload.get("seed") not in (None, ""):
            try:
                request_payload["seed"] = int(payload.get("seed"))
            except Exception:
                pass
        sampler = str(
            payload.get("sampler") or payload.get("sampler_name") or ""
        ).strip()
        if sampler:
            request_payload["sampler_name"] = sampler
        if model and model != "stable-diffusion:configured-backend":
            request_payload["override_settings"] = {"sd_model_checkpoint": model}
        return request_payload

    def openai_image_response(
        self,
        upstream_payload: dict[str, object],
        *,
        requested_model: str,
        upstream: str,
        attempts: list[str],
        allow_nsfw: bool,
        content_rating: str,
        safety_profile: str,
    ) -> dict[str, object]:
        data: list[dict[str, str]] = []
        raw_data = upstream_payload.get("data")
        if isinstance(raw_data, list):
            for item in raw_data:
                if isinstance(item, dict):
                    if str(item.get("b64_json") or "").strip():
                        data.append({"b64_json": str(item.get("b64_json"))})
                    elif str(item.get("url") or "").strip():
                        data.append({"url": str(item.get("url"))})
                elif str(item or "").strip():
                    data.append({"b64_json": str(item)})
        raw_images = upstream_payload.get("images")
        if not data and isinstance(raw_images, list):
            for item in raw_images:
                image = str(item or "").strip()
                if image:
                    data.append({"b64_json": image})
        info_doc: dict[str, object] = {}
        info = upstream_payload.get("info")
        if isinstance(info, str) and info.strip():
            try:
                parsed_info = json.loads(info)
                if isinstance(parsed_info, dict):
                    info_doc = parsed_info
            except Exception:
                info_doc = {}
        elif isinstance(info, dict):
            info_doc = info
        model = (
            str(upstream_payload.get("model") or "").strip()
            or str(info_doc.get("sd_model_name") or "").strip()
            or str(info_doc.get("sd_model_checkpoint") or "").strip()
            or requested_model
            or "stable-diffusion:configured-backend"
        )
        image_count = len(data)
        output_shape = "complete" if image_count else "empty"
        return {
            "created": int(time.time()),
            "model": model,
            "data": data,
            "usage": {
                "usage_bucket": "offline_local",
                "image_count": image_count,
            },
            "norllama": {
                "capability": "image_generate",
                "mode": "image_generation_proxy",
                "selected_provider": "norllama",
                "selected_model": model,
                "selected_worker": self.app.host_alias(upstream),
                "frontdoor": "https://llm.home.arpa",
                "peer_path": [self.app.host_alias(item) for item in attempts],
                "usage_bucket": "offline_local",
                "cloud_proxy": False,
                "fallback_used": False,
                "output_shape": output_shape,
                "verifier_result": "pass" if image_count else "fail",
                "image_count": image_count,
                "allow_nsfw": allow_nsfw,
                "content_rating": content_rating,
                "safety_profile": safety_profile,
                "upstream": upstream,
                "attempts": attempts,
            },
        }

    def embedding_candidates(
        self, model: str
    ) -> tuple[list[str], list[dict], set[str]]:
        bases, rows = self.app.ollama_candidate_bases(model or None)
        peer_bases, peer_rows = self.peer_candidate_bases()
        return (
            bases + peer_bases,
            rows + peer_rows,
            {normalize_base_url(base) for base in peer_bases},
        )

    def request_embedding(
        self,
        *,
        model: str,
        input_value: object,
        keep_alive: str = "30m",
    ) -> tuple[dict[str, object] | None, str, list[str], list[dict]]:
        candidates, rows, peer_bases = self.embedding_candidates(model)
        attempted: list[str] = []
        request_body = json.dumps(
            {
                "model": model,
                "input": input_value,
                "keep_alive": keep_alive,
            }
        ).encode("utf-8")
        for base in candidates:
            attempted.append(base)
            headers = {"Content-Type": "application/json"}
            if normalize_base_url(base) in peer_bases:
                headers = self.peer_forward_headers(headers)
            try:
                status, _response_headers, response_body = self.request_upstream(
                    base,
                    "/api/embed",
                    headers=headers,
                    body=request_body,
                    method="POST",
                )
            except Exception:
                continue
            if status >= 500 or status == 404:
                continue
            try:
                payload = json.loads(response_body.decode("utf-8", errors="replace"))
            except Exception:
                continue
            if isinstance(payload, dict) and (
                payload.get("embeddings") or payload.get("embedding")
            ):
                return payload, base, attempted, rows
        return None, "", attempted, rows

    def embedding_vectors(self, payload: dict[str, object]) -> list[list[float]]:
        raw = payload.get("embeddings")
        if raw is None:
            raw = payload.get("embedding")
        if not isinstance(raw, list):
            return []
        if raw and all(isinstance(item, (int, float)) for item in raw):
            return [[float(item) for item in raw]]
        vectors: list[list[float]] = []
        for row in raw:
            if isinstance(row, list) and all(
                isinstance(item, (int, float)) for item in row
            ):
                vectors.append([float(item) for item in row])
        return vectors

    def handle_openai_embeddings(self, body: bytes) -> None:
        payload = self.parse_json_body(body)
        if payload is None:
            return
        model = (
            str(payload.get("model") or DEFAULT_EMBEDDING_MODEL).strip()
            or DEFAULT_EMBEDDING_MODEL
        )
        input_value = payload.get("input")
        if input_value is None:
            input_value = payload.get("prompt")
        if input_value is None:
            self.send_json(
                HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_input"}
            )
            return
        keep_alive = str(payload.get("keep_alive") or "30m").strip() or "30m"
        self._model_hint = model
        upstream_payload, upstream, attempts, rows = self.request_embedding(
            model=model,
            input_value=input_value,
            keep_alive=keep_alive,
        )
        if upstream_payload is None:
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "ok": False,
                    "error": "embedding_model_unavailable",
                    "model": model,
                    "attempts": attempts,
                    "candidates": self.app.public_candidate_rows("ollama", rows),
                },
            )
            return
        vectors = self.embedding_vectors(upstream_payload)
        data = [
            {
                "object": "embedding",
                "index": index,
                "embedding": vector,
            }
            for index, vector in enumerate(vectors)
        ]
        prompt_count = int(upstream_payload.get("prompt_eval_count") or 0)
        self.send_json(
            HTTPStatus.OK,
            {
                "object": "list",
                "data": data,
                "model": str(upstream_payload.get("model") or model),
                "usage": {
                    "prompt_tokens": prompt_count,
                    "total_tokens": prompt_count,
                },
                "norllama": {
                    "capability": "embed",
                    "upstream": upstream,
                    "attempts": attempts,
                },
            },
            extra_headers={
                "X-Norllama-Upstream": upstream,
                "X-Norllama-Attempts": ",".join(attempts),
            },
        )

    def document_text(self, value: object) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("text", "content", "document"):
                text = str(value.get(key) or "").strip()
                if text:
                    return text
        return str(value or "").strip()

    def cosine_score(self, left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        n = min(len(left), len(right))
        dot = sum(left[i] * right[i] for i in range(n))
        left_norm = sum(left[i] * left[i] for i in range(n)) ** 0.5
        right_norm = sum(right[i] * right[i] for i in range(n)) ** 0.5
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)

    def native_rerank_candidates(self) -> tuple[list[str], list[dict], set[str]]:
        health_bases, health_rows = self.app.rerank_candidate_bases()
        configured_local = [
            normalize_base_url(base)
            for base in self.app.rerank_bases
            if normalize_base_url(base)
        ]
        ordered_local = unique_items([*health_bases, *configured_local])
        static_peer_bases: list[str] = []
        if int(getattr(self, "_peer_hop", 0)) < self.app.max_peer_hops:
            static_peer_bases = [
                normalize_base_url(base)
                for base in self.app.peer_bases
                if normalize_base_url(base)
            ]
        rows = list(health_rows)
        known = {
            normalize_base_url(str(row.get("base_url") or ""))
            for row in rows
            if isinstance(row, dict)
        }
        for base in ordered_local:
            if base and base not in known:
                rows.append(
                    {"base_url": base, "status": "configured", "source": "rerank_bases"}
                )
                known.add(base)
        for base in static_peer_bases:
            if base and base not in known:
                rows.append(
                    {
                        "base_url": base,
                        "status": "configured_peer",
                        "source": "peer_bases",
                    }
                )
                known.add(base)
        return (
            ordered_local + static_peer_bases,
            rows,
            {normalize_base_url(base) for base in static_peer_bases},
        )

    def public_rerank_candidate_rows(self, rows: list[dict]) -> list[dict]:
        public_rows: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            if not self.app.expose_upstream_details:
                item.pop("base_url", None)
            public_rows.append(item)
        return public_rows

    def safety_candidates(self) -> tuple[list[str], list[dict], set[str]]:
        health_bases, health_rows = self.app.safety_candidate_bases()
        configured_local = [
            normalize_base_url(base)
            for base in self.app.safety_bases
            if normalize_base_url(base)
        ]
        ordered_local = unique_items([*health_bases, *configured_local])
        static_peer_bases: list[str] = []
        if int(getattr(self, "_peer_hop", 0)) < self.app.max_peer_hops:
            static_peer_bases = [
                normalize_base_url(base)
                for base in self.app.peer_bases
                if normalize_base_url(base)
            ]
        rows = list(health_rows)
        known = {
            normalize_base_url(str(row.get("base_url") or ""))
            for row in rows
            if isinstance(row, dict)
        }
        for base in ordered_local:
            if base and base not in known:
                rows.append(
                    {"base_url": base, "status": "configured", "source": "safety_bases"}
                )
                known.add(base)
        for base in static_peer_bases:
            if base and base not in known:
                rows.append(
                    {
                        "base_url": base,
                        "status": "configured_peer",
                        "source": "peer_bases",
                    }
                )
                known.add(base)
        return (
            ordered_local + static_peer_bases,
            rows,
            {normalize_base_url(base) for base in static_peer_bases},
        )

    def public_safety_candidate_rows(self, rows: list[dict]) -> list[dict]:
        public_rows: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            if not self.app.expose_upstream_details:
                item.pop("base_url", None)
            public_rows.append(item)
        return public_rows

    def safety_text(self, payload: dict[str, object]) -> str:
        for key in ("text", "prompt", "input", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split()).strip()
        messages = payload.get("messages")
        if isinstance(messages, list):
            parts: list[str] = []
            for message in messages:
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    parts.append(" ".join(content.split()).strip())
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and isinstance(item.get("text"), str):
                            text = " ".join(str(item.get("text") or "").split()).strip()
                            if text:
                                parts.append(text)
            if parts:
                return "\n".join(parts)
        return ""

    def request_safety_classification(
        self,
        *,
        payload: dict[str, object],
        model: str,
    ) -> tuple[dict[str, object] | None, str, list[str], list[dict], str]:
        candidates, rows, peer_bases = self.safety_candidates()
        attempted: list[str] = []
        request_payload = dict(payload)
        request_payload["model"] = model
        request_body = json.dumps(request_payload).encode("utf-8")
        last_error = "no_safety_candidates" if not candidates else ""
        for base in candidates:
            attempted.append(base)
            normalized = normalize_base_url(base)
            is_peer = normalized in peer_bases
            headers = {"Content-Type": "application/json"}
            upstream_path = "/v1/safety/classify" if is_peer else "/v1/safety/classify"
            if is_peer:
                headers = self.peer_forward_headers(headers)
            else:
                key = self.app.safety_key(base)
                if not key:
                    last_error = "missing_safety_key"
                    continue
                headers["Authorization"] = f"Bearer {key}"
            try:
                status, _response_headers, response_body = self.request_upstream(
                    base,
                    upstream_path,
                    headers=headers,
                    body=request_body,
                    method="POST",
                )
            except Exception as exc:
                last_error = str(exc)
                continue
            if status >= 500 or status == 404:
                last_error = f"http_{status}"
                continue
            try:
                response = json.loads(response_body.decode("utf-8", errors="replace"))
            except Exception as exc:
                last_error = f"invalid_json:{exc}"
                continue
            if not isinstance(response, dict):
                last_error = "non_object_response"
                continue
            if status >= 400:
                last_error = str(
                    response.get("error") or response.get("status") or f"http_{status}"
                )
                continue
            if str(response.get("schema") or "") == "norllama.safety-classification.v1":
                return response, base, attempted, rows, ""
            last_error = "missing_safety_schema"
        return None, "", attempted, rows, last_error

    def handle_safety_classify(self, body: bytes) -> None:
        payload = self.parse_json_body(body)
        if payload is None:
            return
        text = self.safety_text(payload)
        if not text:
            self.send_json(
                HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_text"}
            )
            return
        request_payload = dict(payload)
        request_payload["text"] = text
        requested_model = (
            str(payload.get("model") or QWEN3GUARD_MODEL).strip() or QWEN3GUARD_MODEL
        )
        self._model_hint = requested_model
        response, upstream, attempts, rows, error = self.request_safety_classification(
            payload=request_payload,
            model=requested_model,
        )
        if response is None:
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "ok": False,
                    "error": "safety_model_unavailable",
                    "model": requested_model,
                    "attempts": attempts,
                    "native_safety_error": error,
                    "candidates": self.public_safety_candidate_rows(rows),
                    "norllama": {
                        "capability": "safety",
                        "selected_provider": "norllama",
                        "selected_model": requested_model,
                        "usage_bucket": "offline_local",
                        "cloud_proxy": False,
                        "fallback_used": True,
                        "fallback_reason": error or "safety_unavailable",
                        "native_safety_error": error,
                        "output_shape": "error",
                        "verifier_result": "fail",
                    },
                },
            )
            return
        result_model = str(response.get("model") or requested_model).strip()
        if result_model.startswith("/"):
            result_model = requested_model
        response["model"] = result_model or requested_model
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        response["usage"] = {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
            "usage_bucket": "offline_local",
        }
        response["norllama"] = {
            "capability": "safety",
            "task_kind": "safety_privacy_classify",
            "selected_provider": "norllama",
            "selected_model": response["model"],
            "selected_worker": self.app.host_alias(upstream),
            "frontdoor": "https://llm.home.arpa",
            "peer_path": [self.app.host_alias(item) for item in attempts],
            "usage_bucket": "offline_local",
            "cloud_proxy": False,
            "fallback_used": False,
            "fallback_reason": "",
            "output_shape": "complete",
            "verifier_result": "pass",
            "upstream": upstream,
            "attempts": attempts,
        }
        self.send_json(
            HTTPStatus.OK,
            response,
            extra_headers={
                "X-Norllama-Upstream": upstream,
                "X-Norllama-Attempts": ",".join(attempts),
            },
        )

    def request_native_rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int,
        model: str,
    ) -> tuple[dict[str, object] | None, str, list[str], list[dict], str]:
        candidates, rows, peer_bases = self.native_rerank_candidates()
        attempted: list[str] = []
        request_body = json.dumps(
            {
                "query": query,
                "documents": documents,
                "top_n": top_n,
                "model": model,
            }
        ).encode("utf-8")
        last_error = "no_native_rerank_candidates" if not candidates else ""
        for base in candidates:
            attempted.append(base)
            normalized = normalize_base_url(base)
            is_peer = normalized in peer_bases
            headers = {"Content-Type": "application/json"}
            upstream_path = "/v1/rerank" if is_peer else "/rerank"
            if is_peer:
                headers = self.peer_forward_headers(headers)
            else:
                key = self.app.rerank_key(base)
                if not key:
                    last_error = "missing_rerank_key"
                    continue
                headers["Authorization"] = f"Bearer {key}"
            try:
                status, _response_headers, response_body = self.request_upstream(
                    base,
                    upstream_path,
                    headers=headers,
                    body=request_body,
                    method="POST",
                )
            except Exception as exc:
                last_error = str(exc)
                continue
            if status >= 500 or status == 404:
                last_error = f"http_{status}"
                continue
            try:
                payload = json.loads(response_body.decode("utf-8", errors="replace"))
            except Exception as exc:
                last_error = f"invalid_json:{exc}"
                continue
            if not isinstance(payload, dict):
                last_error = "non_object_response"
                continue
            if status >= 400:
                last_error = str(
                    payload.get("error") or payload.get("status") or f"http_{status}"
                )
                continue
            if isinstance(payload.get("results"), list):
                return payload, base, attempted, rows, ""
            last_error = "missing_results"
        return None, "", attempted, rows, last_error

    def handle_rerank(self, body: bytes) -> None:
        payload = self.parse_json_body(body)
        if payload is None:
            return
        query = str(payload.get("query") or payload.get("input") or "").strip()
        raw_documents = payload.get("documents")
        if raw_documents is None:
            raw_documents = payload.get("candidates")
        if raw_documents is None:
            raw_documents = payload.get("texts")
        documents = raw_documents if isinstance(raw_documents, list) else []
        if not query or not documents:
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "missing_query_or_documents"},
            )
            return
        doc_texts = [self.document_text(item) for item in documents]
        doc_texts = [item for item in doc_texts if item]
        if not doc_texts:
            self.send_json(
                HTTPStatus.BAD_REQUEST, {"ok": False, "error": "empty_documents"}
            )
            return
        requested_model = (
            str(payload.get("model") or DEFAULT_RERANK_MODEL).strip()
            or DEFAULT_RERANK_MODEL
        )
        embedding_model = str(payload.get("embedding_model") or "").strip()
        if not embedding_model:
            if (
                "rerank" in requested_model.lower()
                or "reranker" in requested_model.lower()
            ):
                embedding_model = DEFAULT_EMBEDDING_MODEL
            else:
                embedding_model = requested_model
        top_n_raw = payload.get("top_n", payload.get("top_k"))
        try:
            top_n = int(top_n_raw) if top_n_raw is not None else len(doc_texts)
        except Exception:
            top_n = len(doc_texts)
        top_n = max(1, min(top_n, len(doc_texts)))
        prefer_native = str(
            payload.get("score_method") or payload.get("ranker") or ""
        ).strip().lower() not in {
            "cosine",
            "embedding_cosine",
        }
        native_attempts: list[str] = []
        native_rows: list[dict] = []
        native_error = ""
        if prefer_native:
            self._model_hint = requested_model
            (
                native_payload,
                native_upstream,
                native_attempts,
                native_rows,
                native_error,
            ) = self.request_native_rerank(
                query=query,
                documents=doc_texts,
                top_n=top_n,
                model=requested_model,
            )
            if native_payload is not None:
                result_model = str(
                    native_payload.get("model") or requested_model
                ).strip()
                if result_model.startswith("/"):
                    result_model = requested_model
                response = dict(native_payload)
                response["model"] = result_model or requested_model
                response["object"] = response.get("object") or "list"
                usage = (
                    response.get("usage")
                    if isinstance(response.get("usage"), dict)
                    else {}
                )
                response["usage"] = {
                    "document_count": int(
                        usage.get("document_count") or len(doc_texts)
                    ),
                    "total_tokens": int(usage.get("total_tokens") or 0),
                    "usage_bucket": "offline_local",
                }
                response["norllama"] = {
                    "capability": "rerank",
                    "score_method": str(
                        response.get("score_method") or "cross_encoder"
                    ),
                    "selected_provider": "norllama",
                    "selected_model": response["model"],
                    "selected_worker": self.app.host_alias(native_upstream),
                    "frontdoor": "https://llm.home.arpa",
                    "peer_path": [
                        self.app.host_alias(item) for item in native_attempts
                    ],
                    "usage_bucket": "offline_local",
                    "cloud_proxy": False,
                    "fallback_used": False,
                    "output_shape": "complete",
                    "verifier_result": "pass",
                    "upstream": native_upstream,
                    "attempts": native_attempts,
                }
                self.send_json(
                    HTTPStatus.OK,
                    response,
                    extra_headers={
                        "X-Norllama-Upstream": native_upstream,
                        "X-Norllama-Attempts": ",".join(native_attempts),
                        "X-Norllama-Score-Method": str(
                            response["norllama"]["score_method"]
                        ),
                    },
                )
                return
        keep_alive = str(payload.get("keep_alive") or "30m").strip() or "30m"
        self._model_hint = embedding_model
        upstream_payload, upstream, attempts, rows = self.request_embedding(
            model=embedding_model,
            input_value=[query, *doc_texts],
            keep_alive=keep_alive,
        )
        if upstream_payload is None:
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "ok": False,
                    "error": "rerank_embedding_model_unavailable",
                    "model": requested_model,
                    "embedding_model": embedding_model,
                    "attempts": attempts,
                    "native_rerank_attempts": native_attempts,
                    "native_rerank_error": native_error,
                    "native_rerank_preferred": prefer_native,
                    "native_rerank_candidates": self.public_rerank_candidate_rows(
                        native_rows
                    ),
                    "candidates": self.app.public_candidate_rows("ollama", rows),
                },
            )
            return
        vectors = self.embedding_vectors(upstream_payload)
        if len(vectors) < len(doc_texts) + 1:
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "ok": False,
                    "error": "rerank_embedding_response_incomplete",
                    "model": requested_model,
                    "embedding_model": embedding_model,
                    "vector_count": len(vectors),
                    "document_count": len(doc_texts),
                },
            )
            return
        query_vector = vectors[0]
        results = []
        for index, vector in enumerate(vectors[1 : len(doc_texts) + 1]):
            raw_score = self.cosine_score(query_vector, vector)
            results.append(
                {
                    "index": index,
                    "relevance_score": round(
                        max(0.0, min(1.0, (raw_score + 1.0) / 2.0)), 6
                    ),
                    "raw_cosine": round(raw_score, 6),
                    "document": doc_texts[index],
                }
            )
        results.sort(
            key=lambda item: (-float(item["relevance_score"]), int(item["index"]))
        )
        prompt_count = int(upstream_payload.get("prompt_eval_count") or 0)
        self.send_json(
            HTTPStatus.OK,
            {
                "object": "list",
                "model": requested_model,
                "embedding_model": embedding_model,
                "results": results[:top_n],
                "usage": {
                    "prompt_tokens": prompt_count,
                    "total_tokens": prompt_count,
                },
                "norllama": {
                    "capability": "rerank",
                    "score_method": "embedding_cosine",
                    "upstream": upstream,
                    "attempts": attempts,
                    "selected_provider": "norllama",
                    "selected_model": embedding_model,
                    "selected_worker": self.app.host_alias(upstream),
                    "frontdoor": "https://llm.home.arpa",
                    "peer_path": [self.app.host_alias(item) for item in attempts],
                    "usage_bucket": "offline_local",
                    "cloud_proxy": False,
                    "fallback_used": bool(prefer_native),
                    "fallback_reason": "native_rerank_unavailable"
                    if prefer_native
                    else "",
                    "output_shape": "complete",
                    "verifier_result": "pass",
                    "native_rerank_attempts": native_attempts,
                    "native_rerank_error": native_error,
                },
            },
            extra_headers={
                "X-Norllama-Upstream": upstream,
                "X-Norllama-Attempts": ",".join(attempts),
            },
        )

    def handle_prefetch(self, body: bytes) -> None:
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception as exc:
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "invalid_json", "detail": str(exc)},
            )
            return
        model = str(payload.get("model") or "").strip()
        if not model:
            self.send_json(
                HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_model"}
            )
            return
        self._model_hint = model
        keep_alive = str(payload.get("keep_alive") or "30m").strip() or "30m"
        num_ctx_raw = payload.get("num_ctx")
        num_ctx = (
            int(num_ctx_raw)
            if isinstance(num_ctx_raw, int) and num_ctx_raw > 0
            else None
        )
        timeout_raw = payload.get("timeout_s", payload.get("timeout"))
        timeout_s = (
            float(timeout_raw)
            if isinstance(timeout_raw, (int, float)) and float(timeout_raw) > 0
            else None
        )
        base, rows = self.app.choose_ollama_base(model)
        if not base:
            peer_bases, peer_rows = self.peer_candidate_bases(model)
            if peer_bases:
                peer_base = peer_bases[0]
                job, started_job = self.app.start_prefetch_job(
                    kind="peer_prefetch",
                    model=model,
                    base_url=peer_base,
                    upstream_path="/v1/prefetch",
                    request_body=body,
                    keep_alive=keep_alive,
                    num_ctx=num_ctx,
                    timeout_s=timeout_s or self.app.peer_timeout_s,
                    priority=getattr(self, "_priority", "normal"),
                    request_id=getattr(self, "_request_id", ""),
                )
                self._activity_extra = {
                    "mode": "prefetch_submit",
                    "model": model,
                    "prefetch_upstream": peer_base,
                    "prefetch_job_id": str(job.get("job_id") or ""),
                    "prefetch_job_status": str(job.get("status") or ""),
                    **({"prefetch_timeout_s": timeout_s} if timeout_s else {}),
                }
                self.send_json(
                    HTTPStatus.ACCEPTED,
                    {
                        "ok": True,
                        "mode": "prefetch",
                        "status": "accepted",
                        "job_status": job.get("status"),
                        "job_id": job.get("job_id"),
                        "started": started_job,
                        "model": model,
                        "keep_alive": keep_alive,
                        **(
                            {"upstream": peer_base}
                            if self.app.expose_upstream_details
                            else {}
                        ),
                        "status_url": f"/v1/prefetch/status?job_id={urllib.parse.quote(str(job.get('job_id') or ''))}",
                        "job": job,
                    },
                )
                return
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "ok": False,
                    "error": "ollama_model_unavailable",
                    "model": model,
                    "candidates": self.app.public_candidate_rows(
                        "ollama", rows + peer_rows
                    ),
                },
            )
            return
        warm_payload: dict[str, object] = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "stream": False,
            "keep_alive": keep_alive,
            "think": "low" if model.startswith("gpt-oss:") else False,
            "options": {
                "temperature": 0,
                "top_k": 1,
                "top_p": 0.1,
                "seed": 7,
                "num_predict": 16,
            },
        }
        if num_ctx is not None:
            warm_payload["options"]["num_ctx"] = num_ctx
        job, started_job = self.app.start_prefetch_job(
            kind="ollama_prefetch",
            model=model,
            base_url=base,
            upstream_path="/api/chat",
            request_body=json.dumps(warm_payload).encode("utf-8"),
            keep_alive=keep_alive,
            num_ctx=num_ctx,
            timeout_s=timeout_s,
            priority=getattr(self, "_priority", "normal"),
            request_id=getattr(self, "_request_id", ""),
        )
        self._activity_extra = {
            "mode": "prefetch_submit",
            "model": model,
            "prefetch_upstream": base,
            "prefetch_job_id": str(job.get("job_id") or ""),
            "prefetch_job_status": str(job.get("status") or ""),
            **({"prefetch_timeout_s": timeout_s} if timeout_s else {}),
        }
        self.send_json(
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "mode": "prefetch",
                "status": "accepted",
                "job_status": job.get("status"),
                "job_id": job.get("job_id"),
                "started": started_job,
                "model": model,
                "keep_alive": keep_alive,
                **({"upstream": base} if self.app.expose_upstream_details else {}),
                "status_url": f"/v1/prefetch/status?job_id={urllib.parse.quote(str(job.get('job_id') or ''))}",
                "job": job,
            },
        )

    def handle_evict(self, body: bytes) -> None:
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception as exc:
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "invalid_json", "detail": str(exc)},
            )
            return
        model = str(payload.get("model") or "").strip()
        if not model:
            self.send_json(
                HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_model"}
            )
            return
        self._model_hint = model
        timeout_raw = payload.get("timeout_s", payload.get("timeout"))
        timeout_s = (
            float(timeout_raw)
            if isinstance(timeout_raw, (int, float)) and float(timeout_raw) > 0
            else None
        )
        bases, rows = self.app.choose_ollama_bases_for_model(model)
        if not bases:
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "ok": False,
                    "error": "ollama_model_unavailable",
                    "model": model,
                    "candidates": self.app.public_candidate_rows("ollama", rows),
                },
            )
            return
        results: list[dict[str, object]] = []
        worst_status = HTTPStatus.OK
        for base in bases:
            evict_payload = {
                "model": model,
                "prompt": "",
                "stream": False,
                "keep_alive": 0,
            }
            started = time.perf_counter()
            status, response_headers, response_body = self.request_upstream(
                base,
                "/api/generate",
                headers={"Content-Type": "application/json"},
                body=json.dumps(evict_payload).encode("utf-8"),
                method="POST",
                timeout_s=timeout_s,
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            worst_status = max(worst_status, status)
            metrics = extract_ollama_metrics(
                response_body, response_headers.get("Content-Type", "application/json")
            )
            results.append(
                {
                    "status": status,
                    "request_duration_ms": elapsed_ms,
                    "ollama_metrics": metrics,
                    "response": extract_jsonish_final_object(response_body) or {},
                    **({"upstream": base} if self.app.expose_upstream_details else {}),
                }
            )
        self._activity_extra = {
            "mode": "evict",
            "model": model,
            "evict_hosts": [item["upstream"] for item in results],
            **({"evict_timeout_s": timeout_s} if timeout_s else {}),
        }
        self.send_json(
            worst_status,
            {
                "ok": all(200 <= int(item["status"]) < 300 for item in results),
                "mode": "evict",
                "model": model,
                "results": results,
            },
        )

    def handle_ollama_compat_post(self, upstream_path: str, body: bytes) -> None:
        content_type = (
            self.headers.get("Content-Type", "").strip() or "application/json"
        )
        model = self.extract_ollama_model(body)
        if model:
            self._model_hint = model
        if content_type.startswith("application/json") and upstream_path in {
            "/api/chat",
            "/v1/chat/completions",
        }:
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                normalized_payload, changed = normalize_chat_payload_for_local_qwen(
                    payload
                )
                if changed:
                    body = json.dumps(normalized_payload).encode("utf-8")
        bases, rows = self.app.ollama_candidate_bases(model)
        peer_bases, peer_rows = self.peer_candidate_bases(model)
        candidates = bases + peer_bases
        if not candidates:
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "ok": False,
                    "error": "ollama_model_unavailable"
                    if model
                    else "ollama_unavailable",
                    "model": model,
                    "candidates": self.app.public_candidate_rows(
                        "ollama", rows + peer_rows
                    ),
                },
            )
            return
        self.forward_candidates(
            candidates,
            upstream_path,
            body=body,
            headers={"Content-Type": content_type},
            method="POST",
            peer_bases={normalize_base_url(base) for base in peer_bases},
        )

    def handle_native_qwen_openai_chat(
        self,
        payload: dict[str, object],
        candidates: list[str],
        peer_bases: set[str],
    ) -> None:
        model = str(payload.get("model") or "").strip()
        request_body = json.dumps(openai_chat_payload_to_ollama(payload)).encode(
            "utf-8"
        )
        attempted: list[str] = []
        last: tuple[int, dict[str, str], bytes] | None = None
        last_base = ""
        for base in candidates:
            attempted.append(base)
            headers = {"Content-Type": "application/json"}
            if normalize_base_url(base) in peer_bases:
                headers = self.peer_forward_headers(headers)
            try:
                status, response_headers, response_body = self.request_upstream(
                    base,
                    "/api/chat",
                    headers=headers,
                    body=request_body,
                    method="POST",
                )
            except Exception as exc:
                last = (
                    int(HTTPStatus.BAD_GATEWAY),
                    {"Content-Type": "application/json; charset=utf-8"},
                    json.dumps(
                        {
                            "ok": False,
                            "error": "upstream_unavailable",
                            "detail": str(exc),
                        }
                    ).encode("utf-8"),
                )
                last_base = base
                continue
            last = (status, response_headers, response_body)
            last_base = base
            if status == 503 or status >= 500:
                continue
            if status < 200 or status >= 300:
                self.send_upstream(
                    status,
                    response_headers,
                    response_body,
                    extra_headers={
                        "X-Norllama-Upstream": base,
                        "X-Norllama-Attempts": ",".join(attempted),
                    },
                )
                return
            try:
                upstream_payload = json.loads(
                    response_body.decode("utf-8", errors="replace")
                )
            except Exception as exc:
                self.send_json(
                    HTTPStatus.BAD_GATEWAY,
                    {
                        "ok": False,
                        "error": "native_qwen_bridge_invalid_json",
                        "detail": str(exc),
                        "model": model,
                    },
                    extra_headers={
                        "X-Norllama-Upstream": base,
                        "X-Norllama-Attempts": ",".join(attempted),
                    },
                )
                return
            if not isinstance(upstream_payload, dict):
                self.send_json(
                    HTTPStatus.BAD_GATEWAY,
                    {
                        "ok": False,
                        "error": "native_qwen_bridge_invalid_payload",
                        "model": model,
                    },
                    extra_headers={
                        "X-Norllama-Upstream": base,
                        "X-Norllama-Attempts": ",".join(attempted),
                    },
                )
                return
            response = ollama_chat_payload_to_openai(upstream_payload, model=model)
            response["norllama"]["upstream"] = base
            response["norllama"]["attempts"] = list(attempted)
            self._activity_extra = {
                "mode": "native_qwen_bridge",
                "model": model,
                "think_disabled": True,
                "upstream_path": "/api/chat",
                "output_shape": response["norllama"].get("output_shape"),
            }
            self.send_json(
                HTTPStatus.OK,
                response,
                extra_headers={
                    "X-Norllama-Upstream": base,
                    "X-Norllama-Attempts": ",".join(attempted),
                },
            )
            return
        if last is None:
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {"ok": False, "error": "no_upstream_candidates", "model": model},
            )
            return
        self.send_upstream(
            last[0],
            last[1],
            last[2],
            extra_headers={
                "X-Norllama-Upstream": last_base,
                "X-Norllama-Attempts": ",".join(attempted),
            },
        )

    def handle_unified_chat(self, body: bytes) -> None:
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as exc:
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "invalid_json", "detail": str(exc)},
            )
            return
        model = str(payload.get("model") or "").strip()
        if model:
            self._model_hint = model
        payload, changed = normalize_chat_payload_for_local_qwen(payload)
        if changed:
            body = json.dumps(payload).encode("utf-8")
        ds4_models = self.app.ds4_model_ids()
        if (
            model in ds4_models
            or model.startswith("deepseek-v4")
            or model == "deepseek-chat"
        ):
            bases, rows = self.app.ds4_candidate_bases(model or None)
            peer_bases, peer_rows = self.peer_candidate_bases(model or None)
            candidates = bases + peer_bases
            if not candidates:
                self.send_json(
                    HTTPStatus.BAD_GATEWAY,
                    {
                        "ok": False,
                        "error": "ds4_unavailable",
                        "model": model or None,
                        "candidates": self.app.public_candidate_rows(
                            "ds4", rows + peer_rows
                        ),
                    },
                )
                return
            self.forward_candidates(
                candidates,
                "/v1/chat/completions",
                body=body,
                headers={"Content-Type": "application/json"},
                method="POST",
                peer_bases={normalize_base_url(base) for base in peer_bases},
            )
            return
        bases, rows = self.app.ollama_candidate_bases(model or None)
        peer_bases, peer_rows = self.peer_candidate_bases(model or None)
        candidates = bases + peer_bases
        if not candidates:
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "ok": False,
                    "error": "ollama_model_unavailable"
                    if model
                    else "ollama_unavailable",
                    "model": model or None,
                    "candidates": self.app.public_candidate_rows(
                        "ollama", rows + peer_rows
                    ),
                },
            )
            return
        if should_disable_qwen_thinking(model) and not bool(payload.get("stream")):
            self.handle_native_qwen_openai_chat(
                payload,
                candidates,
                {normalize_base_url(base) for base in peer_bases},
            )
            return
        self.forward_candidates(
            candidates,
            "/v1/chat/completions",
            body=body,
            headers={"Content-Type": "application/json"},
            method="POST",
            peer_bases={normalize_base_url(base) for base in peer_bases},
        )

    def parse_audio_upload(self, body: bytes) -> tuple[bytes, str, str]:
        content_type = self.headers.get("Content-Type", "").strip()
        if content_type.startswith("multipart/form-data"):
            media = BytesParser(policy=email.policy.default).parsebytes(
                f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode(
                    "utf-8"
                )
                + body
            )
            if not media.is_multipart():
                raise RuntimeError("invalid multipart payload")
            for part in media.iter_parts():
                disposition, params = split_header_params(
                    part.get("Content-Disposition", "")
                )
                if disposition != "form-data" or params.get("name") != "file":
                    continue
                filename = params.get("filename") or "upload.bin"
                payload = part.get_payload(decode=True) or b""
                mime = part.get_content_type() or guess_content_type(filename)
                return payload, filename, mime
            raise RuntimeError("multipart upload missing file field")
        filename = self.headers.get("X-Filename", "").strip() or "upload.bin"
        mime = content_type or guess_content_type(filename)
        return body, filename, mime

    def handle_unified_transcribe(self, body: bytes) -> None:
        try:
            payload, filename, mime = self.parse_audio_upload(body)
        except Exception as exc:
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "invalid_audio_upload", "detail": str(exc)},
            )
            return
        candidates, rows = self.app.transcribe_candidate_bases()
        if not candidates:
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "ok": False,
                    "error": "transcribe_unavailable",
                    "candidates": self.app.public_candidate_rows("transcribe", rows),
                },
            )
            return
        last: tuple[int, dict[str, str], bytes] | None = None
        attempted: list[str] = []
        last_base: str | None = None
        for base in candidates:
            key = self.app.transcribe_key(base)
            if not key:
                continue
            attempted.append(base)
            result = self.request_upstream(
                base,
                "/transcribe",
                body=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": mime,
                    "X-Filename": filename,
                },
                method="POST",
            )
            last = result
            last_base = base
            if result[0] == 503 or result[0] >= 500:
                continue
            self.send_upstream(
                result[0],
                result[1],
                result[2],
                extra_headers={
                    "X-Norllama-Upstream": base,
                    "X-Norllama-Attempts": ",".join(attempted),
                },
            )
            return
        peer_bases, peer_rows = self.peer_candidate_bases()
        if peer_bases:
            self.forward_candidates(
                peer_bases,
                "/transcribe",
                body=payload,
                headers={
                    "Content-Type": mime,
                    "X-Filename": filename,
                },
                method="POST",
                peer_bases={normalize_base_url(base) for base in peer_bases},
            )
            return
        if last is None:
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": "missing_transcribe_key"},
            )
            return
        self.send_upstream(
            last[0],
            last[1],
            last[2],
            extra_headers={
                "X-Norllama-Upstream": last_base or "",
                "X-Norllama-Attempts": ",".join(attempted),
            },
        )

    def handle_ocr(self, path: str, body: bytes) -> None:
        candidates, rows = self.app.ocr_candidate_bases()
        content_type = (
            self.headers.get("Content-Type", "").strip() or "application/octet-stream"
        )
        filename = (
            self.headers.get("X-Filename", "").strip()
            or self.headers.get("X-Upload-Filename", "").strip()
            or "upload.bin"
        )
        parsed = urllib.parse.urlsplit(path)
        upstream_path = "/ocr" + (f"?{parsed.query}" if parsed.query else "")
        last: tuple[int, dict[str, str], bytes] | None = None
        attempted: list[str] = []
        last_base: str | None = None
        for base in candidates:
            key = self.app.ocr_key(base)
            if not key:
                continue
            attempted.append(base)
            result = self.request_upstream(
                base,
                upstream_path,
                body=body,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": content_type,
                    "X-Filename": filename,
                },
                method="POST",
            )
            last = result
            last_base = base
            if result[0] == 503 or result[0] >= 500:
                continue
            activity_extra: dict[str, object] = {
                "mode": "ocr_proxy",
                "capability": "ocr",
                "model": "paddleocr:PP-OCRv6",
                "filename": filename,
                "upstream_path": "/ocr",
            }
            if (
                result[0] >= 200
                and result[0] < 300
                and "json" in str(result[1].get("Content-Type") or "").lower()
            ):
                try:
                    doc = json.loads(result[2].decode("utf-8", errors="replace"))
                    if isinstance(doc, dict):
                        for key_name in (
                            "engine",
                            "family",
                            "tier",
                            "device",
                            "media_type",
                            "line_count",
                            "frame_count",
                        ):
                            if key_name in doc:
                                activity_extra[f"ocr_{key_name}"] = doc.get(key_name)
                        text = str(doc.get("text") or doc.get("merged_text") or "")
                        activity_extra["output_shape"] = (
                            "complete" if text.strip() else "empty"
                        )
                except Exception:
                    pass
            self._activity_extra = activity_extra
            self.send_upstream(
                result[0],
                result[1],
                result[2],
                extra_headers={
                    "X-Norllama-Upstream": base,
                    "X-Norllama-Attempts": ",".join(attempted),
                },
            )
            return
        peer_bases, peer_rows = self.peer_candidate_bases()
        if peer_bases:
            self.forward_candidates(
                peer_bases,
                path,
                body=body,
                headers={
                    "Content-Type": content_type,
                    "X-Filename": filename,
                },
                method="POST",
                peer_bases={normalize_base_url(base) for base in peer_bases},
            )
            return
        if last is None:
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "ok": False,
                    "error": "ocr_unavailable",
                    "candidates": self.app.public_candidate_rows("ocr", rows),
                },
            )
            return
        self.send_upstream(
            last[0],
            last[1],
            last[2],
            extra_headers={
                "X-Norllama-Upstream": last_base or "",
                "X-Norllama-Attempts": ",".join(attempted),
            },
        )

    def handle_image_generation(self, body: bytes) -> None:
        payload = self.parse_json_body(body)
        if payload is None:
            return
        prompt = self.prompt_from_payload(payload)
        if not prompt:
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "missing_prompt"},
            )
            return
        requested_model = (
            str(payload.get("model") or "stable-diffusion:configured-backend").strip()
            or "stable-diffusion:configured-backend"
        )
        allow_nsfw = self.image_allow_nsfw(payload)
        content_rating = self.image_content_rating(payload)
        safety_profile = self.image_safety_profile(
            payload, content_rating=content_rating
        )
        self._model_hint = requested_model
        upstream_payload = self.stable_diffusion_payload(
            payload, prompt=prompt, model=requested_model
        )
        request_body = json.dumps(upstream_payload).encode("utf-8")
        timeout_s = self.image_timeout_from_payload(payload)
        candidates, rows = self.app.image_candidate_bases()
        attempted: list[str] = []
        last_status = 0
        last_error = "no_image_candidates" if not candidates else ""
        for base in candidates:
            attempted.append(base)
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Norllama-Allow-NSFW": "true" if allow_nsfw else "false",
                "X-Norllama-Content-Rating": content_rating,
                "X-Norllama-Safety-Profile": safety_profile,
            }
            key = self.app.image_key(base)
            if key:
                headers["Authorization"] = f"Bearer {key}"
            try:
                status, response_headers, response_body = self.request_upstream(
                    base,
                    "/sdapi/v1/txt2img",
                    headers=headers,
                    body=request_body,
                    method="POST",
                    timeout_s=timeout_s,
                )
            except Exception as exc:
                last_error = str(exc)[:240]
                continue
            last_status = status
            if status == 404 or status >= 500:
                last_error = f"http_{status}"
                continue
            if status >= 400:
                last_error = response_body.decode("utf-8", errors="replace")[:240]
                break
            content_type = str(response_headers.get("Content-Type") or "")
            if "json" not in content_type.lower():
                last_error = "non_json_image_response"
                continue
            try:
                response_doc = json.loads(
                    response_body.decode("utf-8", errors="replace")
                )
            except Exception as exc:
                last_error = f"invalid_json:{exc}"
                continue
            if not isinstance(response_doc, dict):
                last_error = "non_object_image_response"
                continue
            response = self.openai_image_response(
                response_doc,
                requested_model=requested_model,
                upstream=base,
                attempts=attempted,
                allow_nsfw=allow_nsfw,
                content_rating=content_rating,
                safety_profile=safety_profile,
            )
            image_count = int((response.get("usage") or {}).get("image_count") or 0)
            if image_count <= 0:
                last_error = "empty_image_response"
                continue
            self._activity_extra = {
                "mode": "image_generation_proxy",
                "capability": "image_generate",
                "model": str(response.get("model") or requested_model),
                "image_count": image_count,
                "output_shape": "complete",
                "allow_nsfw": allow_nsfw,
                "content_rating": content_rating,
                "safety_profile": safety_profile,
            }
            self.send_json(
                HTTPStatus.OK,
                response,
                extra_headers={
                    "X-Norllama-Upstream": base,
                    "X-Norllama-Attempts": ",".join(attempted),
                    "X-Norllama-Worker-Id": self.app.host_alias(base),
                },
            )
            return
        peer_bases, peer_rows = self.peer_candidate_bases()
        if peer_bases:
            self.forward_candidates(
                peer_bases,
                "/v1/images/generations",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Norllama-Allow-NSFW": "true" if allow_nsfw else "false",
                    "X-Norllama-Content-Rating": content_rating,
                    "X-Norllama-Safety-Profile": safety_profile,
                },
                method="POST",
                peer_bases={normalize_base_url(base) for base in peer_bases},
            )
            return
        self._activity_extra = {
            "mode": "image_generation_proxy",
            "capability": "image_generate",
            "model": requested_model,
            "image_count": 0,
            "output_shape": "error",
            "fallback_used": False,
            "fallback_reason": last_error or "image_generation_unavailable",
            "allow_nsfw": allow_nsfw,
            "content_rating": content_rating,
            "safety_profile": safety_profile,
        }
        self.send_json(
            HTTPStatus.BAD_GATEWAY,
            {
                "ok": False,
                "error": "image_generation_unavailable",
                "model": requested_model,
                "last_status": last_status,
                "last_error": last_error,
                "candidates": self.app.public_candidate_rows("image", rows + peer_rows),
                "norllama": {
                    "capability": "image_generate",
                    "mode": "image_generation_proxy",
                    "selected_provider": "norllama",
                    "selected_model": requested_model,
                    "selected_worker": "",
                    "frontdoor": "https://llm.home.arpa",
                    "peer_path": [],
                    "usage_bucket": "offline_local",
                    "cloud_proxy": False,
                    "fallback_used": False,
                    "fallback_reason": last_error or "image_generation_unavailable",
                    "output_shape": "error",
                    "verifier_result": "fail",
                    "image_count": 0,
                    "allow_nsfw": allow_nsfw,
                    "content_rating": content_rating,
                    "safety_profile": safety_profile,
                    "attempts": attempted,
                },
            },
            extra_headers={"X-Norllama-Attempts": ",".join(attempted)},
        )

    def handle_media(self, path: str, body: bytes) -> None:
        candidates, rows = self.app.media_candidate_bases()
        if not candidates:
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "ok": False,
                    "error": "media_unavailable",
                    "candidates": self.app.public_candidate_rows("media", rows),
                },
            )
            return
        upstream_path = path[len("/media") :]
        content_type = (
            self.headers.get("Content-Type", "").strip() or "application/octet-stream"
        )
        last: tuple[int, dict[str, str], bytes] | None = None
        attempted: list[str] = []
        last_base: str | None = None
        for base in candidates:
            key = self.app.media_key(base)
            if not key:
                continue
            attempted.append(base)
            result = self.request_upstream(
                base,
                upstream_path,
                body=body,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": content_type,
                },
                method=self.command,
            )
            last = result
            last_base = base
            if result[0] == 503 or result[0] >= 500:
                continue
            self.send_upstream(
                result[0],
                result[1],
                result[2],
                extra_headers={
                    "X-Norllama-Upstream": base,
                    "X-Norllama-Attempts": ",".join(attempted),
                },
            )
            return
        peer_bases, peer_rows = self.peer_candidate_bases()
        if peer_bases:
            self.forward_candidates(
                peer_bases,
                path,
                body=body,
                headers={"Content-Type": content_type},
                method=self.command,
                peer_bases={normalize_base_url(base) for base in peer_bases},
            )
            return
        if last is None:
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": "missing_media_key"},
            )
            return
        self.send_upstream(
            last[0],
            last[1],
            last[2],
            extra_headers={
                "X-Norllama-Upstream": last_base or "",
                "X-Norllama-Attempts": ",".join(attempted),
            },
        )

    def allowed_methods(self, path: str) -> list[str]:
        if path in {
            "/",
            "/ui",
            "/health",
            "/healthz",
            "/v1/models",
            "/v1/overview",
            "/v1/catalog",
            "/v1/capabilities",
            "/v1/warm-policy",
            "/v1/activity",
            "/v1/prefetch/status",
            "/api/version",
            "/api/tags",
            "/api/ps",
        }:
            return ["GET", "HEAD", "OPTIONS"]
        if path in {
            "/v1/chat/completions",
            "/v1/prefetch",
            "/v1/evict",
            "/transcribe",
            "/v1/audio/transcriptions",
            "/api/chat",
            "/api/generate",
            "/api/show",
            "/api/embed",
            "/api/embeddings",
            "/v1/embeddings",
            "/v1/rerank",
            "/rerank",
            "/v1/safety/classify",
            "/safety/classify",
            "/v1/images/generations",
        }:
            return ["POST", "OPTIONS"]
        if path.startswith("/media/"):
            return ["POST", "OPTIONS"]
        if path.startswith("/ollama/") or path.startswith("/ds4/"):
            return ["GET", "HEAD", "POST", "OPTIONS"]
        return ["OPTIONS"]

    def do_GET(self) -> None:
        self.begin_request()
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path in {"/", "/ui"}:
            self.send_html(HTTPStatus.OK, self.app.render_ui_html())
            return
        if parsed.path == "/health":
            self.send_json(HTTPStatus.OK, self.app.health())
            return
        if parsed.path == "/healthz":
            self.send_json(HTTPStatus.OK, self.app.healthz())
            return
        if parsed.path == "/api/version":
            self.send_json(HTTPStatus.OK, gateway_version_doc())
            return
        if parsed.path == "/api/tags":
            self.send_json(HTTPStatus.OK, self.app.merged_ollama_tags())
            return
        if parsed.path == "/api/ps":
            query = urllib.parse.parse_qs(parsed.query or "")
            scope = str((query.get("scope") or ["local"])[0] or "local").strip().lower()
            include_peers = scope in {"mesh", "fleet", "peers", "all"} or str(
                (query.get("mesh") or [""])[0]
            ).lower() in {"1", "true", "yes", "on"}
            self.send_json(
                HTTPStatus.OK, self.app.merged_ollama_ps(include_peers=include_peers)
            )
            return
        if parsed.path == "/v1/models":
            self.send_json(HTTPStatus.OK, self.app.public_models_doc())
            return
        if parsed.path == "/v1/overview":
            self.send_json(HTTPStatus.OK, self.app.overview())
            return
        if parsed.path == "/v1/catalog":
            self.send_json(HTTPStatus.OK, self.app.catalog())
            return
        if parsed.path == "/v1/capabilities":
            self.send_json(HTTPStatus.OK, self.app.capabilities_doc())
            return
        if parsed.path == "/v1/warm-policy":
            self.send_json(HTTPStatus.OK, self.app.warm_policy_doc())
            return
        if parsed.path.startswith("/v1/capabilities/"):
            contract_id = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1])
            payload = self.app.capability_contract_doc(contract_id)
            if payload is None:
                self.send_json(
                    HTTPStatus.NOT_FOUND,
                    {"error": "unknown_capability_contract", "contract": contract_id},
                )
                return
            self.send_json(HTTPStatus.OK, payload)
            return
        if parsed.path == "/v1/activity":
            query = urllib.parse.parse_qs(parsed.query or "")
            try:
                limit = int((query.get("limit") or ["20"])[0])
            except Exception:
                limit = 20
            tool_only = str(
                (query.get("tool_only") or query.get("tools") or [""])[0]
            ).lower() in {"1", "true", "yes", "on"}
            self.send_json(
                HTTPStatus.OK,
                self.app.recent_activity(limit, tool_only=tool_only),
            )
            return
        if parsed.path == "/v1/prefetch/status":
            query = urllib.parse.parse_qs(parsed.query or "")
            try:
                limit = int((query.get("limit") or ["20"])[0])
            except Exception:
                limit = 20
            self.send_json(
                HTTPStatus.OK,
                self.app.prefetch_jobs_doc(
                    job_id=(query.get("job_id") or [""])[0],
                    model=(query.get("model") or [""])[0],
                    limit=limit,
                ),
            )
            return
        if parsed.path.startswith("/ollama/"):
            local_bases, _ = self.app.ollama_candidate_bases()
            peer_bases, _ = self.peer_candidate_bases()
            candidates = local_bases + peer_bases
            if not candidates:
                self.send_json(
                    HTTPStatus.BAD_GATEWAY, {"ok": False, "error": "ollama_unavailable"}
                )
                return
            self.forward_candidates(
                candidates,
                parsed.path[len("/ollama") :]
                + (f"?{parsed.query}" if parsed.query else ""),
                peer_bases={normalize_base_url(base) for base in peer_bases},
            )
            return
        if parsed.path.startswith("/ds4/"):
            bases, rows = self.app.ds4_candidate_bases()
            peer_bases, peer_rows = self.peer_candidate_bases()
            candidates = bases + peer_bases
            if not candidates:
                self.send_json(
                    HTTPStatus.BAD_GATEWAY,
                    {
                        "ok": False,
                        "error": "ds4_unavailable",
                        "candidates": self.app.public_candidate_rows(
                            "ds4", rows + peer_rows
                        ),
                    },
                )
                return
            self.forward_candidates(
                candidates,
                parsed.path[len("/ds4") :]
                + (f"?{parsed.query}" if parsed.query else ""),
                peer_bases={normalize_base_url(base) for base in peer_bases},
            )
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_HEAD(self) -> None:
        self.begin_request()
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path in {"/", "/ui"}:
            body = self.app.render_ui_html().encode("utf-8")
            self.send_head_only(
                HTTPStatus.OK,
                content_type="text/html; charset=utf-8",
                content_length=len(body),
            )
            return
        if parsed.path == "/health":
            body = json.dumps(self.app.health(), sort_keys=True).encode("utf-8")
            self.send_head_only(
                HTTPStatus.OK, content_type="application/json", content_length=len(body)
            )
            return
        if parsed.path == "/healthz":
            body = json.dumps(self.app.healthz(), sort_keys=True).encode("utf-8")
            self.send_head_only(
                HTTPStatus.OK, content_type="application/json", content_length=len(body)
            )
            return
        if parsed.path == "/api/version":
            body = json.dumps(gateway_version_doc(), sort_keys=True).encode("utf-8")
            self.send_head_only(
                HTTPStatus.OK, content_type="application/json", content_length=len(body)
            )
            return
        if parsed.path == "/api/tags":
            body = json.dumps(self.app.merged_ollama_tags(), sort_keys=True).encode(
                "utf-8"
            )
            self.send_head_only(
                HTTPStatus.OK, content_type="application/json", content_length=len(body)
            )
            return
        if parsed.path == "/api/ps":
            body = json.dumps(self.app.merged_ollama_ps(), sort_keys=True).encode(
                "utf-8"
            )
            self.send_head_only(
                HTTPStatus.OK, content_type="application/json", content_length=len(body)
            )
            return
        if parsed.path == "/v1/models":
            body = json.dumps(self.app.public_models_doc(), sort_keys=True).encode(
                "utf-8"
            )
            self.send_head_only(
                HTTPStatus.OK, content_type="application/json", content_length=len(body)
            )
            return
        if parsed.path == "/v1/overview":
            body = json.dumps(self.app.overview(), sort_keys=True).encode("utf-8")
            self.send_head_only(
                HTTPStatus.OK, content_type="application/json", content_length=len(body)
            )
            return
        if parsed.path == "/v1/catalog":
            body = json.dumps(self.app.catalog(), sort_keys=True).encode("utf-8")
            self.send_head_only(
                HTTPStatus.OK, content_type="application/json", content_length=len(body)
            )
            return
        if parsed.path == "/v1/capabilities":
            body = json.dumps(self.app.capabilities_doc(), sort_keys=True).encode(
                "utf-8"
            )
            self.send_head_only(
                HTTPStatus.OK, content_type="application/json", content_length=len(body)
            )
            return
        if parsed.path == "/v1/warm-policy":
            body = json.dumps(self.app.warm_policy_doc(), sort_keys=True).encode(
                "utf-8"
            )
            self.send_head_only(
                HTTPStatus.OK, content_type="application/json", content_length=len(body)
            )
            return
        if parsed.path == "/v1/activity":
            query = urllib.parse.parse_qs(parsed.query or "")
            try:
                limit = int((query.get("limit") or ["20"])[0])
            except Exception:
                limit = 20
            tool_only = str(
                (query.get("tool_only") or query.get("tools") or [""])[0]
            ).lower() in {"1", "true", "yes", "on"}
            body = json.dumps(
                self.app.recent_activity(limit, tool_only=tool_only),
                sort_keys=True,
            ).encode(
                "utf-8",
            )
            self.send_head_only(
                HTTPStatus.OK, content_type="application/json", content_length=len(body)
            )
            return
        if parsed.path == "/v1/prefetch/status":
            query = urllib.parse.parse_qs(parsed.query or "")
            try:
                limit = int((query.get("limit") or ["20"])[0])
            except Exception:
                limit = 20
            body = json.dumps(
                self.app.prefetch_jobs_doc(
                    job_id=(query.get("job_id") or [""])[0],
                    model=(query.get("model") or [""])[0],
                    limit=limit,
                ),
                sort_keys=True,
            ).encode("utf-8")
            self.send_head_only(
                HTTPStatus.OK, content_type="application/json", content_length=len(body)
            )
            return
        if parsed.path.startswith("/ollama/"):
            local_bases, _ = self.app.ollama_candidate_bases()
            peer_bases, _ = self.peer_candidate_bases()
            candidates = local_bases + peer_bases
            if not candidates:
                self.send_json(
                    HTTPStatus.BAD_GATEWAY, {"ok": False, "error": "ollama_unavailable"}
                )
                return
            self.forward_candidates(
                candidates,
                parsed.path[len("/ollama") :]
                + (f"?{parsed.query}" if parsed.query else ""),
                method="HEAD",
                peer_bases={normalize_base_url(base) for base in peer_bases},
            )
            return
        if parsed.path.startswith("/ds4/"):
            bases, rows = self.app.ds4_candidate_bases()
            peer_bases, peer_rows = self.peer_candidate_bases()
            candidates = bases + peer_bases
            if not candidates:
                self.send_json(
                    HTTPStatus.BAD_GATEWAY,
                    {
                        "ok": False,
                        "error": "ds4_unavailable",
                        "candidates": self.app.public_candidate_rows(
                            "ds4", rows + peer_rows
                        ),
                    },
                )
                return
            self.forward_candidates(
                candidates,
                parsed.path[len("/ds4") :]
                + (f"?{parsed.query}" if parsed.query else ""),
                method="HEAD",
                peer_bases={normalize_base_url(base) for base in peer_bases},
            )
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_OPTIONS(self) -> None:
        self.begin_request()
        parsed = urllib.parse.urlsplit(self.path)
        allow = ", ".join(self.allowed_methods(parsed.path))
        self.send_empty(
            HTTPStatus.NO_CONTENT,
            extra_headers={
                "Allow": allow,
                "X-Norllama-Async-Supported": "true"
                if parsed.path in {"/v1/prefetch", "/v1/prefetch/status"}
                else "false",
                "X-Norllama-Priority-Mode": "hint_only",
                "X-Norllama-Priority-Levels": ",".join(sorted(PRIORITY_LEVELS)),
            },
        )

    def do_POST(self) -> None:
        self.begin_request()
        parsed = urllib.parse.urlsplit(self.path)
        body = self.read_body()
        if parsed.path == "/v1/prefetch":
            self.handle_prefetch(body)
            return
        if parsed.path == "/v1/evict":
            self.handle_evict(body)
            return
        if parsed.path == "/v1/chat/completions":
            self.handle_unified_chat(body)
            return
        if parsed.path == "/v1/images/generations":
            self.handle_image_generation(body)
            return
        if parsed.path in {"/v1/embeddings", "/api/embeddings"}:
            self.handle_openai_embeddings(body)
            return
        if parsed.path in {"/v1/rerank", "/rerank"}:
            self.handle_rerank(body)
            return
        if parsed.path in {"/v1/safety/classify", "/safety/classify"}:
            self.handle_safety_classify(body)
            return
        if parsed.path in {"/v1/ocr", "/ocr"}:
            self.handle_ocr(
                parsed.path + (f"?{parsed.query}" if parsed.query else ""), body
            )
            return
        if parsed.path in {"/api/chat", "/api/generate", "/api/show", "/api/embed"}:
            self.handle_ollama_compat_post(parsed.path, body)
            return
        if parsed.path in {"/transcribe", "/v1/audio/transcriptions"}:
            self.handle_unified_transcribe(body)
            return
        if parsed.path.startswith("/media/"):
            self.handle_media(
                parsed.path + (f"?{parsed.query}" if parsed.query else ""), body
            )
            return
        if parsed.path.startswith("/ollama/"):
            content_type = (
                self.headers.get("Content-Type", "").strip() or "application/json"
            )
            model = self.extract_ollama_model(body)
            bases, rows = self.app.ollama_candidate_bases(model)
            peer_bases, peer_rows = self.peer_candidate_bases()
            candidates = bases + peer_bases
            if not candidates:
                self.send_json(
                    HTTPStatus.BAD_GATEWAY,
                    {
                        "ok": False,
                        "error": "ollama_model_unavailable"
                        if model
                        else "ollama_unavailable",
                        "model": model,
                        "candidates": self.app.public_candidate_rows(
                            "ollama", rows + peer_rows
                        ),
                    },
                )
                return
            self.forward_candidates(
                candidates,
                parsed.path[len("/ollama") :]
                + (f"?{parsed.query}" if parsed.query else ""),
                body=body,
                headers={"Content-Type": content_type},
                method="POST",
                peer_bases={normalize_base_url(base) for base in peer_bases},
            )
            return
        if parsed.path.startswith("/ds4/"):
            content_type = (
                self.headers.get("Content-Type", "").strip() or "application/json"
            )
            bases, rows = self.app.ds4_candidate_bases()
            peer_bases, peer_rows = self.peer_candidate_bases()
            candidates = bases + peer_bases
            if not candidates:
                self.send_json(
                    HTTPStatus.BAD_GATEWAY,
                    {
                        "ok": False,
                        "error": "ds4_unavailable",
                        "candidates": self.app.public_candidate_rows(
                            "ds4", rows + peer_rows
                        ),
                    },
                )
                return
            self.forward_candidates(
                candidates,
                parsed.path[len("/ds4") :]
                + (f"?{parsed.query}" if parsed.query else ""),
                body=body,
                headers={"Content-Type": content_type},
                method="POST",
                peer_bases={normalize_base_url(base) for base in peer_bases},
            )
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Norllama unified Spark gateway.")
    parser.add_argument(
        "--listen-host", default=os.getenv("NORLLAMA_BIND", DEFAULT_BIND)
    )
    parser.add_argument(
        "--listen-port",
        type=int,
        default=int(os.getenv("NORLLAMA_PORT", str(DEFAULT_PORT))),
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    app = App()
    app.bind = args.listen_host
    app.port = args.listen_port
    server = ThreadingHTTPServer((app.bind, app.port), Handler)
    server.app = app  # type: ignore[attr-defined]
    print(f"norllama listening on {app.bind}:{app.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
