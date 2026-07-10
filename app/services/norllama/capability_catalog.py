from __future__ import annotations

from copy import deepcopy
from typing import Any

CATALOG_SCHEMA = "norman.norllama.capability-catalog.v1"

CAPABILITY_CLASSES = {
    "chat": "general text generation and synthesis",
    "code": "coding operator, repo reasoning, and patch drafting",
    "judge": "heavy local verification and high-value review",
    "embed": "text memory embeddings",
    "rerank": "text evidence reranking",
    "vl_embed": "visual and multimodal memory embeddings",
    "vl_rerank": "visual and multimodal evidence reranking",
    "ocr": "OCR and visual document parsing",
    "doc_parse": "PDF to Markdown and structured document extraction",
    "gui_ground": "screen coordinate grounding",
    "asr": "speech recognition",
    "tts": "local speech synthesis",
    "safety": "prompt and response safety checks",
    "prompt_injection": "hostile-context and prompt-injection detection",
    "forecast": "time-series and observability forecasting",
    "graph": "estate graph and relational graph inference",
    "network": "network, DNS, packet, and flow intelligence",
    "vision_geometry": "segmentation, depth, and visual matching",
    "world": "browser/world/action simulation",
    "image_generate": "local image generation through a Stable Diffusion-compatible service",
}

CAPABILITY_MODELS: list[dict[str, Any]] = [
    {
        "capability": "fast_agent_router",
        "class": "chat",
        "model": "nvidia/Qwen3.6-35B-A3B-NVFP4",
        "runtime_model": "qwen3.6:35b-a3b-q4_K_M",
        "priority": "p0",
        "residency": "resident",
        "target_worker": "spark-151",
        "target_role": "production",
        "use_for": "fast agent routing, planning, filtering, and swarm coordination",
        "guardrail": "Use for routing and draft plans; verify risky work.",
        "default_for": ["plan", "filter", "summarize", "compact", "scout"],
    },
    {
        "capability": "coding_operator",
        "class": "code",
        "model": "nvidia/Qwen3.6-27B-NVFP4",
        "runtime_model": "qwen3.6:27b",
        "priority": "p0",
        "residency": "warm_on_demand",
        "target_worker": "spark-151",
        "target_role": "production",
        "use_for": "default local coding operator and repo reasoning brain",
        "guardrail": "Run tests and verifier checks before final authority.",
        "default_for": ["chat", "code"],
    },
    {
        "capability": "local_heavyweight_judge",
        "class": "judge",
        "model": "nvidia/Qwen3.5-122B-A10B-NVFP4",
        "runtime_model": "qwen3.5:122b-a10b-q4_K_M",
        "priority": "p1",
        "residency": "warm_on_demand",
        "target_worker": "spark-151",
        "target_role": "production",
        "use_for": "heavy local judge, verifier, and escalation reducer",
        "guardrail": "Use for expensive verification and high-value decisions.",
        "default_for": ["verify", "judge"],
    },
    {
        "capability": "text_embedding_heavy",
        "class": "embed",
        "model": "Qwen/Qwen3-Embedding-8B",
        "runtime_model": "bge-m3:latest",
        "priority": "p0",
        "residency": "resident",
        "target_worker": "spark-150",
        "target_role": "production",
        "use_for": "repo, docs, logs, tickets, crawl captures, and agent trace memory",
        "guardrail": "Use as retrieval infrastructure, not as a reasoning authority.",
        "default_for": ["embed"],
    },
    {
        "capability": "text_embedding_fast",
        "class": "embed",
        "model": "Qwen/Qwen3-Embedding-0.6B",
        "priority": "canary",
        "residency": "resident",
        "target_worker": "mac-mini-133",
        "target_role": "fallback",
        "use_for": "tiny fallback embeddings and health canary memory",
        "guardrail": "Fallback path only when heavier embedding lane is unavailable.",
    },
    {
        "capability": "text_rerank_heavy",
        "class": "rerank",
        "model": "BAAI/bge-reranker-v2-m3",
        "runtime_model": "BAAI/bge-reranker-v2-m3",
        "priority": "p0",
        "residency": "service",
        "target_worker": "spark-150",
        "target_role": "production",
        "dispatch": "rerank_proxy",
        "serving_path": "/v1/rerank",
        "use_for": "primary evidence reranking before expensive model calls",
        "guardrail": "Use the native cross-encoder scorer before planner, judge, browser, and cloud escalation; BGE-M3 cosine is degraded fallback only.",
        "default_for": ["rerank"],
    },
    {
        "capability": "text_rerank_fast",
        "class": "rerank",
        "model": "Qwen/Qwen3-Reranker-0.6B",
        "priority": "canary",
        "residency": "resident",
        "target_worker": "mac-mini-133",
        "target_role": "fallback",
        "use_for": "fast local reranking and degraded fallback reranking",
        "guardrail": "Use for fast path and fallback; promote difficult ranking to 8B.",
    },
    {
        "capability": "vl_embedding",
        "class": "vl_embed",
        "model": "Qwen/Qwen3-VL-Embedding-8B",
        "priority": "p1",
        "residency": "warm_on_demand",
        "target_worker": "spark-150",
        "target_role": "production",
        "use_for": "screenshot, PDF page, product page, and UI-state memory",
        "guardrail": "Use before multimodal planner sees large visual evidence sets.",
    },
    {
        "capability": "vl_rerank",
        "class": "vl_rerank",
        "model": "Qwen/Qwen3-VL-Reranker-8B",
        "priority": "p1",
        "residency": "warm_on_demand",
        "target_worker": "spark-150",
        "target_role": "production",
        "use_for": "visual/text evidence reranking for screenshots, PDFs, and UI captures",
        "guardrail": "Rank visual evidence before expensive visual reasoning.",
    },
    {
        "capability": "visual_doc_retrieval",
        "class": "doc_parse",
        "model": "nvidia/nemotron-colembed-vl-8b-v2",
        "priority": "p1",
        "residency": "warm_on_demand",
        "target_worker": "spark-150",
        "target_role": "production",
        "use_for": "visually rich PDFs, charts, tables, forms, and reports",
        "guardrail": "Use as retrieval infrastructure; preserve source page evidence.",
    },
    {
        "capability": "ocr_default",
        "class": "ocr",
        "model": "PaddlePaddle/PaddleOCR-VL-1.6",
        "priority": "p1",
        "residency": "warm_on_demand",
        "target_worker": "spark-150",
        "target_role": "production",
        "use_for": "default OCR and document parsing lane",
        "guardrail": "Keep page image and extracted text tied together as evidence.",
        "default_for": ["ocr"],
    },
    {
        "capability": "pdf_markdown",
        "class": "doc_parse",
        "model": "opendatalab/MinerU2.5-Pro-2605-1.2B",
        "priority": "p1",
        "residency": "warm_on_demand",
        "target_worker": "spark-150",
        "target_role": "production",
        "use_for": "PDF-to-Markdown ingestion and document evidence packets",
        "guardrail": "Use for extraction; preserve document provenance and page spans.",
        "default_for": ["doc_parse"],
    },
    {
        "capability": "gui_grounding",
        "class": "gui_ground",
        "model": "ServiceNow/GroundNext-7B-V0",
        "priority": "p1",
        "residency": "warm_on_demand",
        "target_worker": "spark-150",
        "target_role": "production",
        "use_for": "pixel coordinates and GUI element grounding",
        "guardrail": "GroundNext points; another model decides why and whether safe.",
        "default_for": ["gui_ground"],
    },
    {
        "capability": "asr_spark_distil",
        "class": "asr",
        "model": "faster-whisper:distil-large-v3",
        "priority": "p1",
        "residency": "service",
        "target_worker": "spark-150",
        "target_role": "production",
        "dispatch": "transcribe_proxy",
        "use_for": "default Spark-backed Norllama media-pipeline transcription and multilingual ASR",
        "guardrail": "Use faster-whisper for speech-to-text; keep speaker labels and timestamps provisional unless benchmarked.",
        "default_for": ["stt", "asr"],
    },
    {
        "capability": "asr_quality_large",
        "class": "asr",
        "model": "faster-whisper:large-v3",
        "priority": "p1",
        "residency": "service",
        "target_worker": "spark-150",
        "target_role": "production",
        "dispatch": "transcribe_proxy",
        "use_for": "heavier ASR quality lane once a production Spark advertises it",
        "guardrail": "Do not default-route until the matching Spark service and Uplink ASR benchmark are live.",
    },
    {
        "capability": "asr_fast",
        "class": "asr",
        "model": "faster-whisper:base",
        "priority": "canary",
        "residency": "service",
        "target_worker": "mac-mini-133",
        "target_role": "fallback",
        "dispatch": "transcribe_proxy",
        "use_for": "low-latency degraded transcription and command capture",
        "guardrail": "Fallback path only; promote uncertain transcripts to the quality faster-whisper lane.",
    },
    {
        "capability": "tts_voice",
        "class": "tts",
        "model": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "priority": "p2",
        "residency": "cold_only",
        "target_worker": "spark-150",
        "target_role": "production",
        "use_for": "local agent voice output",
        "guardrail": "No TTS lane should gate task completion.",
        "default_for": ["tts"],
    },
    {
        "capability": "stable_diffusion_image_shell",
        "class": "image_generate",
        "model": "stable-diffusion:configured-backend",
        "runtime_model": "stable-diffusion:configured-backend",
        "priority": "p2",
        "residency": "lab",
        "target_worker": "spark-150",
        "target_role": "lab",
        "dispatch": "image_generation_proxy",
        "serving_path": "/v1/images/generations",
        "use_for": "local image generation, UI mockup sketches, thumbnails, and non-authoritative visual drafts",
        "guardrail": "Use only through the Norllama image lane; receipts must show the backend worker and offline_local usage. Adult/NSFW mode must be explicit in request metadata and receipts. Keep lab until a Stable Diffusion backend is live and benchmarked. Image outputs are artifacts, not factual evidence.",
        "default_for": ["image_generate"],
    },
    {
        "capability": "agent_world_simulator",
        "class": "world",
        "model": "Qwen/Qwen-AgentWorld-35B-A3B",
        "runtime_model": "qwen3.6:35b-a3b-q4_K_M",
        "priority": "p2",
        "residency": "lab",
        "target_worker": "spark-150",
        "target_role": "lab",
        "dispatch": "world_proxy",
        "use_for": "simulate action consequences before browser, shell, and workflow execution",
        "guardrail": "Lab only until a real AgentWorld service handler is installed, smoke-tested, benchmark-backed, and schema-checked.",
    },
    {
        "capability": "web_world_simulator",
        "class": "world",
        "model": "Qwen/WebWorld-8B",
        "runtime_model": "qwen3.6:35b-a3b-q4_K_M",
        "priority": "p2",
        "residency": "lab",
        "target_worker": "spark-150",
        "target_role": "lab",
        "dispatch": "world_proxy",
        "use_for": "browser task simulation, page-state prediction, and web-agent rehearsal",
        "guardrail": "Lab only until a real WebWorld service handler is installed, smoke-tested, benchmark-backed, and schema-checked.",
    },
    {
        "capability": "safety_generation",
        "class": "safety",
        "model": "Qwen/Qwen3Guard-Gen-8B",
        "priority": "p1",
        "residency": "warm_on_demand",
        "target_worker": "spark-150",
        "target_role": "lab",
        "use_for": "full prompt and response policy checks",
        "guardrail": "Desired heavier safety judge; do not route by default until installed, smoke-tested, benchmarked, and exposed through a serving path.",
    },
    {
        "capability": "safety_streaming",
        "class": "safety",
        "model": "Qwen/Qwen3Guard-Stream-0.6B",
        "runtime_model": "Qwen/Qwen3Guard-Stream-0.6B",
        "priority": "p0",
        "residency": "service",
        "target_worker": "spark-150",
        "target_role": "production",
        "dispatch": "safety_proxy",
        "serving_path": "/v1/safety/classify",
        "use_for": "prompt safety and prompt-injection triage before tool/browser submit actions and cloud escalation",
        "guardrail": "Fast local safety gate; receipt must show offline_local usage, worker attribution, schema-valid output, and cloud_proxy=false.",
        "default_for": ["safety", "prompt_injection"],
    },
    {
        "capability": "prompt_injection",
        "class": "prompt_injection",
        "model": "qualifire/prompt-injection-sentinel",
        "priority": "blocked",
        "residency": "aspirational",
        "target_worker": "spark-150",
        "target_role": "blocked",
        "use_for": "specialized injection detection for browser, RAG, email, and PDFs",
        "guardrail": "Artifact access is gated; keep aspirational until the model can be installed, smoke-tested, benchmarked, and schema-checked.",
    },
    {
        "capability": "observability_forecast",
        "class": "forecast",
        "model": "Datadog/Toto-2.0-1B",
        "priority": "p2",
        "residency": "cold_only",
        "target_worker": "spark-150",
        "target_role": "production",
        "use_for": "crawler health, queue depth, cost drift, latency, and error spikes",
        "guardrail": "Use for forecasts; keep incident decisions under operator policy.",
        "default_for": ["forecast"],
    },
    {
        "capability": "general_forecast",
        "class": "forecast",
        "model": "amazon/chronos-2",
        "priority": "p2",
        "residency": "cold_only",
        "target_worker": "spark-150",
        "target_role": "production",
        "use_for": "general zero-shot time-series baseline",
        "guardrail": "Compare against Toto for observability series.",
    },
    {
        "capability": "estate_graph",
        "class": "graph",
        "model": "GraphPFN-1.3",
        "priority": "p2",
        "residency": "cold_only",
        "target_worker": "spark-150",
        "target_role": "production",
        "use_for": "small-to-medium cyber estate graph inference",
        "guardrail": "Lab lane until benchmarks prove value on Norman estate data.",
        "default_for": ["graph"],
    },
    {
        "capability": "packet_embeddings",
        "class": "network",
        "model": "PacketCLIP",
        "priority": "p2",
        "residency": "cold_only",
        "target_worker": "spark-150",
        "target_role": "production",
        "use_for": "packet and flow semantic search and anomaly detection",
        "guardrail": "Lab lane; do not automate network actions from this alone.",
        "default_for": ["network"],
    },
    {
        "capability": "dns_model",
        "class": "network",
        "model": "DNS-GT",
        "priority": "p2",
        "residency": "cold_only",
        "target_worker": "spark-150",
        "target_role": "production",
        "use_for": "DGA, passive DNS, resolver drift, and domain graph embeddings",
        "guardrail": "Use as signal, not blocking authority.",
    },
]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _ordered_unique(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = _clean(value)
        if clean and clean not in result:
            result.append(clean)
    return result


def runtime_model_for_catalog_item(item: dict[str, Any]) -> str:
    """Return the concrete Norllama model tag to send at runtime."""

    return _clean(item.get("runtime_model")) or _clean(item.get("model"))


def model_aliases_for_catalog_item(item: dict[str, Any]) -> list[str]:
    aliases = item.get("aliases")
    if not isinstance(aliases, list):
        aliases = []
    return _ordered_unique(
        [
            item.get("model"),
            item.get("runtime_model"),
            item.get("served_model"),
            *aliases,
        ]
    )


def catalog_models() -> list[dict[str, Any]]:
    return [deepcopy(item) for item in CAPABILITY_MODELS]


def catalog_by_model() -> dict[str, dict[str, Any]]:
    by_model: dict[str, dict[str, Any]] = {}
    for item in CAPABILITY_MODELS:
        for model in model_aliases_for_catalog_item(item):
            by_model.setdefault(model, deepcopy(item))
    return by_model


def default_model_for_task_kind(kind: str, *, lightweight: bool = False) -> str:
    clean_kind = _clean(kind).lower()
    if not clean_kind:
        return ""
    matches = [
        item
        for item in CAPABILITY_MODELS
        if clean_kind in {str(value).lower() for value in item.get("default_for", [])}
    ]
    if not matches:
        return ""
    if lightweight:
        for item in matches:
            if item.get("priority") == "canary":
                return runtime_model_for_catalog_item(item)
    return runtime_model_for_catalog_item(matches[0])


def warm_policy_recommendations() -> list[dict[str, Any]]:
    priority_rank = {"p0": 0, "p1": 1, "canary": 2, "p2": 3}
    by_runtime_model: dict[str, dict[str, Any]] = {}
    for item in CAPABILITY_MODELS:
        desired_model = _clean(item.get("model"))
        runtime_model = runtime_model_for_catalog_item(item)
        priority = _clean(item.get("priority")) or "p2"
        existing = by_runtime_model.get(runtime_model)
        if existing:
            existing["desired_models"] = _ordered_unique(
                [*existing.get("desired_models", []), desired_model]
            )
            existing["model_aliases"] = _ordered_unique(
                [
                    *existing.get("model_aliases", []),
                    *model_aliases_for_catalog_item(item),
                ]
            )
            existing["roles"] = _ordered_unique(
                [*existing.get("roles", []), item.get("capability")]
            )
            existing["default_for"] = _ordered_unique(
                [*existing.get("default_for", []), *item.get("default_for", [])]
            )
            if priority_rank.get(priority, 9) < priority_rank.get(
                existing.get("priority"), 9
            ):
                existing["priority"] = priority
                existing["profile"] = _clean(item.get("capability"))
                existing["target_worker"] = _clean(item.get("target_worker"))
                existing["target_role"] = _clean(item.get("target_role"))
                existing["capability"] = _clean(item.get("capability"))
                existing["capability_class"] = _clean(item.get("class"))
                existing["residency"] = _clean(item.get("residency"))
            continue
        by_runtime_model[runtime_model] = {
            "model": runtime_model,
            "desired_model": desired_model,
            "desired_models": [desired_model],
            "model_aliases": model_aliases_for_catalog_item(item),
            "profile": _clean(item.get("capability")),
            "priority": priority,
            "source": "capability_catalog",
            "use_for": _clean(item.get("use_for")),
            "guardrail": _clean(item.get("guardrail")),
            "benchmark_status": "catalog_recommended",
            "target_worker": _clean(item.get("target_worker")),
            "target_role": _clean(item.get("target_role")),
            "capability": _clean(item.get("capability")),
            "capability_class": _clean(item.get("class")),
            "residency": _clean(item.get("residency")),
            "roles": [_clean(item.get("capability"))],
            "default_for": _ordered_unique(item.get("default_for", [])),
        }
    return list(by_runtime_model.values())


def catalog_payload() -> dict[str, Any]:
    models = catalog_models()
    by_class: dict[str, list[str]] = {}
    for item in models:
        class_name = _clean(item.get("class")) or "unknown"
        by_class.setdefault(class_name, []).append(runtime_model_for_catalog_item(item))
    return {
        "schema": CATALOG_SCHEMA,
        "model_count": len(models),
        "classes": deepcopy(CAPABILITY_CLASSES),
        "by_class": by_class,
        "models": models,
        "defaults": {
            kind: default_model_for_task_kind(kind)
            for kind in (
                "plan",
                "chat",
                "code",
                "verify",
                "embed",
                "rerank",
                "ocr",
                "doc_parse",
                "gui_ground",
                "stt",
                "asr",
                "world",
                "web_world",
                "safety",
                "prompt_injection",
                "forecast",
                "graph",
                "network",
                "image_generate",
            )
        },
        "node_intent": {
            "spark-151": "Qwen planner, coding, and heavyweight judge brains",
            "spark-150": "specialist services: embeddings, rerank, OCR/media, safety, perception, forecasting, graph, network, and lab lanes",
            "mac-mini-133": "tiny fallback, canary, degraded ASR, and low-memory health lanes",
        },
    }
