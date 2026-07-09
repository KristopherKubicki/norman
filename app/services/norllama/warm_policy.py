from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.core.config import settings
from app.services.norllama.capability_catalog import (
    catalog_by_model,
    catalog_payload,
    warm_policy_recommendations,
)
from app.services.norllama import gateway
from app.services.norllama.mesh_cache import get_mesh_overview
from app.services.norllama.model_reality import (
    build_model_reality,
    service_evidence_for_catalog_item,
)
from app.services.norllama.route_outcomes import (
    local_route_cooldown,
    normalize_route_outcome,
)

DEFAULT_WARM_RECOMMENDATIONS: list[dict[str, Any]] = [
    {
        "model": "qwen3.6:35b-a3b-q4_K_M",
        "profile": "qwen36_router_local",
        "priority": "p0",
        "source": "fallback",
        "use_for": "interactive local planning, routing, filtering, scout prep, and summarization",
        "guardrail": "Use as the fast production local brain; verify risky work.",
    },
    {
        "model": "qwen3.6:27b",
        "profile": "qwen36_coding_local",
        "priority": "p0",
        "source": "fallback",
        "use_for": "default local coding, repo reasoning, and execution drafting",
        "guardrail": "Run tests and verifier checks before final authority.",
    },
    {
        "model": "qwen3.5:122b-a10b-q4_K_M",
        "profile": "qwen35_heavy_judge_local",
        "priority": "p1",
        "source": "fallback",
        "use_for": "heavy local judge, verifier, and escalation reducer",
        "guardrail": "Use for expensive verification and high-value decisions.",
    },
    {
        "model": "bge-m3:latest",
        "profile": "bge_m3_memory_local",
        "priority": "p0",
        "source": "fallback",
        "use_for": "text embedding and rerank infrastructure for local memory/evidence selection",
        "guardrail": "Use for retrieval infrastructure, not as a reasoning authority.",
    },
    {
        "model": "gemma3:1b",
        "profile": "tiny_canary",
        "priority": "canary",
        "source": "fallback",
        "use_for": "tiny health/canary lane",
        "guardrail": "Do not use as an authority model.",
    },
    {
        "model": "gemma3:4b",
        "profile": "small_canary",
        "priority": "canary",
        "source": "fallback",
        "use_for": "small fallback and canary lane",
        "guardrail": "Do not use as an authority model.",
    },
]

PRIORITY_RANK = {"p0": 0, "p1": 1, "canary": 2, "p2": 3}
SMALL_MODEL_MAX_B = 4
FALLBACK_WORKER_MEMORY_GB = 32
PRODUCTION_WORKER_MEMORY_GB = 64
DEFAULT_PRODUCTION_RESIDENT_LIMIT = 2
DEFAULT_FALLBACK_RESIDENT_LIMIT = 1
BAD_BENCHMARK_STATUSES = {
    "bad",
    "blocked",
    "deprecated",
    "disabled",
    "failed",
    "low_quality",
    "not_recommended",
    "rejected",
    "retired",
    "skip",
    "weak",
}
GOOD_BENCHMARK_STATUSES = {
    "accepted",
    "benchmark_backed",
    "keep_warm",
    "ok",
    "passed",
    "preferred",
    "recommended",
    "selected",
}
ROUTE_GUARDRAIL_LANES = (
    "planner",
    "scout",
    "summarizer",
    "coder",
    "filter",
    "verifier",
    "judge",
    "embedding",
    "rerank",
    "safety",
    "prompt_injection",
    "ocr",
    "doc_parse",
    "gui_ground",
    "speech",
    "forecast",
    "graph",
    "network",
    "world",
    "image_generate",
    "canary",
)
NARROW_SPECIALIST_LANES = {
    "embedding",
    "rerank",
    "safety",
    "prompt_injection",
    "ocr",
    "doc_parse",
    "gui_ground",
    "speech",
    "forecast",
    "graph",
    "network",
    "world",
    "image_generate",
}
LANE_TEXT_MARKERS = {
    "planner": (
        "plan",
        "planner",
        "decomposition",
        "route prep",
        "work decomposition",
    ),
    "scout": ("scout", "research", "status", "inspect", "triage", "preflight"),
    "summarizer": ("summary", "summarize", "summarise", "writeup", "writeups"),
    "coder": ("code", "coder", "patch", "repo", "test", "diff"),
    "filter": ("filter", "classify", "classification", "rank", "rerank", "safety"),
    "verifier": ("verify", "verifier", "judge", "check", "governance"),
    "judge": ("judge", "heavyweight", "final review", "risk review"),
    "embedding": ("embedding", "embed", "memory", "index"),
    "rerank": ("rerank", "rank", "evidence selection"),
    "safety": ("safety", "guard", "moderation", "policy"),
    "prompt_injection": ("prompt injection", "injection", "hostile context"),
    "ocr": ("ocr", "document parsing", "page extraction"),
    "doc_parse": ("pdf", "markdown", "document", "visual document"),
    "gui_ground": ("gui", "screen", "pixel", "grounding"),
    "speech": ("asr", "speech", "voice", "tts"),
    "forecast": ("forecast", "time-series", "observability"),
    "graph": ("graph", "estate", "relational"),
    "network": ("packet", "dns", "network", "traffic"),
    "world": ("world", "simulator", "simulation", "browser rehearsal"),
    "image_generate": ("image", "diffusion", "stable diffusion", "txt2img"),
}
LANE_FAMILY_DEFAULTS = {
    "qwen": ("planner", "scout", "coder", "summarizer"),
    "gemma": ("planner", "scout", "summarizer", "filter", "verifier"),
    "deepseek": ("coder", "planner", "verifier"),
    "llama": ("scout", "summarizer", "canary"),
    "openfugu": ("planner", "canary"),
    "paddle": ("ocr", "doc_parse"),
    "mineru": ("doc_parse",),
    "groundnext": ("gui_ground",),
    "guard": ("safety",),
    "sentinel": ("prompt_injection",),
    "toto": ("forecast",),
    "chronos": ("forecast",),
    "graph": ("graph",),
    "network": ("network",),
    "agentworld": ("world",),
    "webworld": ("world",),
    "stable-diffusion": ("image_generate",),
    "diffusion": ("image_generate",),
    "sdxl": ("image_generate",),
    "txt2img": ("image_generate",),
    "general": ("planner", "scout", "summarizer"),
}
TASK_KIND_ROUTE_LANES = {
    "chat": ("coder", "planner", "summarizer"),
    "code": ("coder", "planner"),
    "scout": ("scout", "planner"),
    "plan": ("planner", "scout"),
    "filter": ("filter", "rerank", "planner"),
    "summarize": ("summarizer", "planner"),
    "compact": ("summarizer", "filter"),
    "verify": ("verifier", "judge"),
    "judge": ("judge", "verifier"),
    "ocr": ("ocr", "doc_parse"),
    "doc_parse": ("doc_parse", "ocr"),
    "stt": ("speech",),
    "asr": ("speech",),
    "tts": ("speech",),
    "embed": ("embedding",),
    "rerank": ("rerank",),
    "safety": ("safety",),
    "prompt_injection": ("prompt_injection", "safety"),
    "gui_ground": ("gui_ground",),
    "forecast": ("forecast",),
    "graph": ("graph",),
    "network": ("network",),
    "world": ("world", "planner", "verifier"),
    "web_world": ("world", "gui_ground", "planner"),
    "browser_sim": ("world", "gui_ground", "planner"),
    "image_generate": ("image_generate",),
    "stable_diffusion": ("image_generate",),
}
ACTION_SELECTION_RANK = {
    "keep_warm": 0,
    "prefetch": 1,
    "observe": 2,
}
POOL_STRATEGIES = {"balanced", "fast", "quality", "resident"}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _endpoint_key(value: Any) -> str:
    raw = _clean(value).rstrip("/")
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw.lower()
    host = (parsed.hostname or "").strip("[]").lower()
    if not host:
        return raw.lower()
    if parsed.port:
        return f"{host}:{parsed.port}"
    if parsed.scheme == "https":
        return f"{host}:443"
    if parsed.scheme == "http":
        return f"{host}:80"
    return host


def _setting_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def _setting_float(
    name: str, default: float, *, minimum: float, maximum: float
) -> float:
    try:
        value = float(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def _setting_bool(name: str, default: bool) -> bool:
    value = getattr(settings, name, default)
    if isinstance(value, bool):
        return value
    return _clean(value).lower() in {"1", "true", "yes", "on"}


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _model_size_b(model: str) -> int | None:
    import re

    sizes = [
        int(match.group(2))
        for match in re.finditer(r"(^|[:/_-])(\d+)b\b", _clean(model).lower())
    ]
    return max(sizes) if sizes else None


def _model_family(model: str) -> str:
    clean = _clean(model).lower()
    if "deepseek" in clean or clean.startswith("ds4"):
        return "deepseek"
    if "qwen" in clean or "coder" in clean:
        return "qwen"
    if "paddleocr" in clean or "paddle" in clean:
        return "paddle"
    if "mineru" in clean:
        return "mineru"
    if "groundnext" in clean or "showui" in clean:
        return "groundnext"
    if "qwen3guard" in clean or "guard" in clean:
        return "guard"
    if "sentinel" in clean:
        return "sentinel"
    if "toto" in clean:
        return "toto"
    if "chronos" in clean:
        return "chronos"
    if "graph" in clean or "kumo" in clean:
        return "graph"
    if "packet" in clean or "dns" in clean or "lens" in clean:
        return "network"
    if "gemma" in clean:
        return "gemma"
    if "openfugu" in clean or "fugu" in clean:
        return "openfugu"
    if "llama" in clean:
        return "llama"
    return "general"


def _public_models_from_mesh(mesh: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for model in mesh.get("models") or []:
        clean = _clean(model)
        if clean and clean not in names:
            names.append(clean)
    for section in [mesh.get("frontdoor") or {}, *(mesh.get("workers") or [])]:
        if not isinstance(section, dict):
            continue
        for model in section.get("models") or []:
            clean = _clean(model)
            if clean and clean not in names:
                names.append(clean)
    return names


def _active_models_from_mesh(mesh: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for worker in mesh.get("workers") or []:
        if not isinstance(worker, dict):
            continue
        for model in worker.get("active_models") or []:
            clean = _clean(model)
            if clean and clean not in names:
                names.append(clean)
    return names


def _worker_models(worker: dict[str, Any], key: str) -> list[str]:
    names: list[str] = []
    for model in worker.get(key) or []:
        clean = _clean(model)
        if clean and clean not in names:
            names.append(clean)
    return names


def _worker_memory_gb(worker: dict[str, Any]) -> int:
    value = _as_int(worker.get("memory_gb"))
    if value is not None:
        return value
    worker_id = _clean(worker.get("id")).lower()
    if "133" in worker_id or "mac" in worker_id:
        return 16
    if "spark" in worker_id:
        return 128
    return 0


def _worker_role(worker: dict[str, Any]) -> str:
    role = _clean(worker.get("role")).lower()
    if role:
        return role
    memory = _worker_memory_gb(worker)
    worker_id = _clean(worker.get("id")).lower()
    if memory and memory <= FALLBACK_WORKER_MEMORY_GB:
        return "fallback"
    if "133" in worker_id or "mac" in worker_id:
        return "fallback"
    if memory >= PRODUCTION_WORKER_MEMORY_GB or "spark" in worker_id:
        return "production"
    return "worker"


def _worker_limit(worker: dict[str, Any]) -> int:
    role = _worker_role(worker)
    if role == "fallback":
        return DEFAULT_FALLBACK_RESIDENT_LIMIT
    return DEFAULT_PRODUCTION_RESIDENT_LIMIT


def _worker_pressure(worker: dict[str, Any]) -> dict[str, Any]:
    active_models = _worker_models(worker, "active_models")
    memory_gb = _worker_memory_gb(worker)
    estimated_gb = 0.0
    unknown = 0
    for model in active_models:
        size_b = _model_size_b(model)
        if size_b is None:
            unknown += 1
            estimated_gb += 4.0
        else:
            estimated_gb += max(1.0, size_b * 0.75 + 2.0)
    limit = _worker_limit(worker)
    high = len(active_models) >= limit
    if memory_gb > 0 and estimated_gb >= memory_gb * 0.78:
        high = True
    state = "high" if high else ("normal" if active_models else "low")
    return {
        "state": state,
        "active_model_count": len(active_models),
        "resident_limit": limit,
        "memory_gb": memory_gb,
        "estimated_active_gb": round(estimated_gb, 1),
        "unknown_model_count": unknown,
    }


def _mesh_workers(mesh: dict[str, Any]) -> list[dict[str, Any]]:
    workers: list[dict[str, Any]] = []
    for item in mesh.get("workers") or []:
        if isinstance(item, dict):
            workers.append(item)
    return workers


def _worker_has_model(worker: dict[str, Any], model: str) -> bool:
    models = _worker_models(worker, "models")
    return _model_matches(model, models)


def _worker_active_model(worker: dict[str, Any], model: str) -> bool:
    return _model_matches(model, _worker_models(worker, "active_models"))


def _worker_public_endpoint(worker: dict[str, Any]) -> str:
    return _clean(
        worker.get("base_url")
        or worker.get("public_base_url")
        or worker.get("endpoint")
        or worker.get("url")
    )


def _service_workers(
    *,
    item: dict[str, Any],
    mesh: dict[str, Any],
    workers: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    catalog_item = catalog_by_model().get(_clean(item.get("model")), {})
    merged_item = dict(catalog_item)
    merged_item.update({key: value for key, value in item.items() if _clean(value)})
    evidence = service_evidence_for_catalog_item(mesh, merged_item)
    worker_ids = set(evidence.get("worker_ids") or [])
    matched = [
        worker
        for worker in workers
        if _clean(worker.get("id") or worker.get("worker_id")) in worker_ids
    ]
    return evidence, matched


def _worker_summary(worker: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _clean(worker.get("id")),
        "role": _worker_role(worker),
        "reachable": bool(worker.get("reachable")),
        "status": _clean(worker.get("status")),
        "model_count": len(_worker_models(worker, "models")),
        "active_models": _worker_models(worker, "active_models")[:8],
        "active_model_count": len(_worker_models(worker, "active_models")),
        "pressure": _worker_pressure(worker),
    }


def _model_matches(model: str, candidates: list[str]) -> bool:
    clean = _clean(model).lower()
    if not clean:
        return False
    tail = clean.rsplit("/", 1)[-1]
    return any(
        clean == _clean(candidate).lower()
        or tail == _clean(candidate).lower().rsplit("/", 1)[-1]
        for candidate in candidates
    )


def _load_json_path(path: str) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return {}
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _load_json_url(url: str, timeout_seconds: float) -> dict[str, Any]:
    response = gateway._requests_get(  # Internal helper preserves local TLS behavior.
        url,
        headers={"Accept": "application/json"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def load_benchmark_packet(
    *,
    path: str = "",
    url: str = "",
    timeout_seconds: float = 5,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the exported Uplink benchmark packet if Norman has one."""

    configured_path = _clean(path) or _clean(
        getattr(settings, "llm_benchmark_packet_path", "")
    )
    configured_url = _clean(url) or _clean(
        getattr(settings, "llm_benchmark_packet_url", "")
    )
    if configured_path:
        try:
            packet = _load_json_path(configured_path)
            if packet:
                return packet, {
                    "status": "loaded",
                    "source": "path",
                    "path": configured_path,
                    "packet_id": _clean(packet.get("packet_id") or packet.get("id"))
                    or _clean(packet.get("generated_at")),
                    "generated_at": _clean(packet.get("generated_at")),
                }
        except Exception as exc:
            path_error = _clean(exc)
        else:
            path_error = "not found"
    else:
        path_error = ""
    if configured_url:
        try:
            packet = _load_json_url(configured_url, timeout_seconds)
            if packet:
                return packet, {
                    "status": "loaded",
                    "source": "url",
                    "url": configured_url,
                    "packet_id": _clean(packet.get("packet_id") or packet.get("id"))
                    or _clean(packet.get("generated_at")),
                    "generated_at": _clean(packet.get("generated_at")),
                }
        except Exception as exc:
            return {}, {
                "status": "error",
                "source": "url",
                "url": configured_url,
                "error": _clean(exc)[:240],
            }
    return {}, {
        "status": "fallback",
        "source": "defaults",
        "path": configured_path,
        "error": path_error[:240],
    }


def _priority_for_role(role: dict[str, Any]) -> str:
    lane = _clean(role.get("lane_id"))
    if lane in {"governance_cluster", "product_information"}:
        return "p1"
    return "p0"


def _upsert_recommendation(
    by_model: dict[str, dict[str, Any]],
    *,
    model: str,
    profile: str = "",
    priority: str = "p1",
    source: str = "benchmark",
    use_for: str = "",
    guardrail: str = "",
    score: Any = None,
    coverage_ratio: Any = None,
    status: str = "",
    benchmark_status: str = "",
    target_worker: str = "",
    target_role: str = "",
    contract_id: str = "",
    lane_id: str = "",
    quality_metrics: dict[str, Any] | None = None,
) -> None:
    clean_model = _clean(model)
    if not clean_model:
        return
    existing = by_model.get(clean_model)
    next_rank = PRIORITY_RANK.get(priority, 9)
    if existing and PRIORITY_RANK.get(existing.get("priority"), 9) <= next_rank:
        roles = existing.setdefault("roles", [])
        role = contract_id or lane_id or use_for
        if role and role not in roles:
            roles.append(role)
        return
    clean_status = _clean(status or benchmark_status)
    metrics_source = quality_metrics if isinstance(quality_metrics, dict) else {}
    quality_metric_keys = (
        "accepted_count",
        "accepted",
        "total_count",
        "row_count",
        "sample_count",
        "count",
        "timeout_rate",
        "timeout_count",
        "timeouts",
        "empty_response_rate",
        "empty_response_count",
        "empty_count",
        "zero_token_rate",
        "zero_token_count",
        "progress_only_rate",
        "progress_only_count",
        "verifier_rejection_rate",
        "verifier_rejection_count",
        "output_shape_valid",
        "cold_start_p95",
        "warm_latency_p95",
    )
    quality_snapshot = {
        key: metrics_source.get(key)
        for key in quality_metric_keys
        if key in metrics_source
    }
    by_model[clean_model] = {
        "model": clean_model,
        "profile": _clean(profile),
        "priority": priority,
        "source": source,
        "use_for": _clean(use_for),
        "guardrail": _clean(guardrail),
        "score": _as_float(score),
        "coverage_ratio": _as_float(coverage_ratio),
        "benchmark_status": clean_status,
        "target_worker": _clean(target_worker),
        "target_role": _clean(target_role),
        "contract_id": _clean(contract_id),
        "lane_id": _clean(lane_id),
        "quality_metrics": quality_snapshot,
        "roles": [item for item in [contract_id, lane_id] if _clean(item)],
    }


def benchmark_recommendations(packet: dict[str, Any]) -> list[dict[str, Any]]:
    by_model: dict[str, dict[str, Any]] = {}
    shareable = packet.get("shareable_view") if isinstance(packet, dict) else {}
    if isinstance(shareable, dict):
        for role in shareable.get("recommended_roles") or []:
            if not isinstance(role, dict):
                continue
            _upsert_recommendation(
                by_model,
                model=_clean(role.get("model")),
                profile=_clean(role.get("profile")),
                priority=_priority_for_role(role),
                source="uplink_benchmark",
                use_for=_clean(role.get("use_for")),
                guardrail=_clean(role.get("guardrail")),
                score=role.get("score") or role.get("score_high"),
                coverage_ratio=role.get("coverage_ratio") or role.get("coverage_high"),
                status=_clean(
                    role.get("status")
                    or role.get("benchmark_status")
                    or role.get("recommendation")
                    or role.get("recommendation_status")
                ),
                target_worker=_clean(
                    role.get("target_worker") or role.get("worker_id")
                ),
                target_role=_clean(role.get("target_role") or role.get("worker_role")),
                lane_id=_clean(role.get("lane_id")),
                quality_metrics=role,
            )
        for section_name in (
            "model_scores",
            "model_rankings",
            "benchmark_results",
            "results",
        ):
            for result_item in shareable.get(section_name) or []:
                if not isinstance(result_item, dict):
                    continue
                _upsert_recommendation(
                    by_model,
                    model=_clean(
                        result_item.get("model")
                        or result_item.get("model_id")
                        or result_item.get("name")
                    ),
                    profile=_clean(result_item.get("profile")),
                    priority=_clean(result_item.get("priority")) or "p1",
                    source="uplink_benchmark",
                    use_for=_clean(
                        result_item.get("use_for")
                        or result_item.get("lane_id")
                        or result_item.get("task")
                    ),
                    guardrail=_clean(result_item.get("guardrail")),
                    score=(
                        result_item.get("score")
                        or result_item.get("weighted_score")
                        or result_item.get("best_weighted_score")
                    ),
                    coverage_ratio=(
                        result_item.get("coverage_ratio") or result_item.get("coverage")
                    ),
                    status=_clean(
                        result_item.get("status")
                        or result_item.get("benchmark_status")
                        or result_item.get("recommendation")
                    ),
                    target_worker=_clean(
                        result_item.get("target_worker") or result_item.get("worker_id")
                    ),
                    target_role=_clean(
                        result_item.get("target_role") or result_item.get("worker_role")
                    ),
                    lane_id=_clean(result_item.get("lane_id")),
                    quality_metrics=result_item,
                )
    for contract in packet.get("capability_contracts") or []:
        if not isinstance(contract, dict):
            continue
        status = _clean(contract.get("status"))
        model = _clean(contract.get("default_model"))
        if not model or status == "pending_benchmark":
            continue
        _upsert_recommendation(
            by_model,
            model=model,
            profile=_clean(contract.get("default_profile")),
            priority="p1",
            source="uplink_benchmark",
            use_for=_clean(contract.get("title") or contract.get("contract_id")),
            guardrail=_clean(contract.get("guardrail")),
            score=contract.get("best_weighted_score"),
            coverage_ratio=None,
            status=status,
            target_worker=_clean(
                contract.get("target_worker") or contract.get("worker_id")
            ),
            target_role=_clean(
                contract.get("target_role") or contract.get("worker_role")
            ),
            contract_id=_clean(contract.get("contract_id")),
            quality_metrics=contract,
        )
    for section_name in (
        "model_scores",
        "model_rankings",
        "benchmark_results",
        "results",
    ):
        for result_item in packet.get(section_name) or []:
            if not isinstance(result_item, dict):
                continue
            _upsert_recommendation(
                by_model,
                model=_clean(
                    result_item.get("model")
                    or result_item.get("model_id")
                    or result_item.get("name")
                ),
                profile=_clean(result_item.get("profile")),
                priority=_clean(result_item.get("priority")) or "p1",
                source="uplink_benchmark",
                use_for=_clean(
                    result_item.get("use_for")
                    or result_item.get("lane_id")
                    or result_item.get("task")
                ),
                guardrail=_clean(result_item.get("guardrail")),
                score=(
                    result_item.get("score")
                    or result_item.get("weighted_score")
                    or result_item.get("best_weighted_score")
                ),
                coverage_ratio=(
                    result_item.get("coverage_ratio") or result_item.get("coverage")
                ),
                status=_clean(
                    result_item.get("status")
                    or result_item.get("benchmark_status")
                    or result_item.get("recommendation")
                ),
                target_worker=_clean(
                    result_item.get("target_worker") or result_item.get("worker_id")
                ),
                target_role=_clean(
                    result_item.get("target_role") or result_item.get("worker_role")
                ),
                lane_id=_clean(result_item.get("lane_id")),
                quality_metrics=result_item,
            )
    result = list(by_model.values())
    result.sort(
        key=lambda item: (
            PRIORITY_RANK.get(item.get("priority"), 9),
            -(_as_float(item.get("score")) or 0.0),
            item["model"],
        )
    )
    return result


def _fallback_recommendations() -> list[dict[str, Any]]:
    recommendations = warm_policy_recommendations()
    seen_models = {_clean(item.get("model")) for item in recommendations}
    for item in DEFAULT_WARM_RECOMMENDATIONS:
        model = _clean(item.get("model"))
        if model and model in seen_models:
            continue
        recommendations.append(dict(item))
        seen_models.add(model)
    return recommendations


def _quality_metric(item: dict[str, Any], *keys: str) -> Any:
    metrics = (
        item.get("quality_metrics")
        if isinstance(item.get("quality_metrics"), dict)
        else {}
    )
    for key in keys:
        if key in item and item.get(key) not in ("", None):
            return item.get(key)
        if key in metrics and metrics.get(key) not in ("", None):
            return metrics.get(key)
    return None


def _quality_int(item: dict[str, Any], *keys: str) -> int | None:
    value = _quality_metric(item, *keys)
    return _as_int(value)


def _quality_float(item: dict[str, Any], *keys: str) -> float | None:
    value = _quality_metric(item, *keys)
    return _as_float(value)


def _quality_bool(item: dict[str, Any], *keys: str) -> bool | None:
    value = _quality_metric(item, *keys)
    if value in ("", None):
        return None
    if isinstance(value, bool):
        return value
    clean = _clean(value).lower()
    if clean in {"1", "true", "yes", "ok", "valid", "pass", "passed"}:
        return True
    if clean in {"0", "false", "no", "invalid", "fail", "failed"}:
        return False
    return None


def _quality_total_count(item: dict[str, Any]) -> int | None:
    total = _quality_int(item, "total_count", "row_count", "sample_count", "count")
    if total is not None:
        return total
    counts = [
        _quality_int(item, "accepted_count", "accepted"),
        _quality_int(item, "timeout_count", "timeouts"),
        _quality_int(item, "empty_response_count", "empty_count"),
        _quality_int(item, "zero_token_count"),
        _quality_int(item, "progress_only_count"),
    ]
    known = [value for value in counts if value is not None]
    return sum(known) if known else None


def _quality_rate(
    item: dict[str, Any],
    *,
    rate_keys: tuple[str, ...],
    count_keys: tuple[str, ...],
    total_count: int | None,
) -> float | None:
    explicit = _quality_float(item, *rate_keys)
    if explicit is not None:
        return explicit
    count = _quality_int(item, *count_keys)
    if count is None or not total_count:
        return None
    return count / max(1, total_count)


def _benchmark_quality_rejection(
    item: dict[str, Any],
    *,
    score: float | None,
    coverage: float | None,
    min_score: float,
    min_coverage: float,
) -> dict[str, Any] | None:
    total_count = _quality_total_count(item)
    accepted_count = _quality_int(item, "accepted_count", "accepted")
    timeout_rate = _quality_rate(
        item,
        rate_keys=("timeout_rate",),
        count_keys=("timeout_count", "timeouts"),
        total_count=total_count,
    )
    empty_rate = _quality_rate(
        item,
        rate_keys=("empty_response_rate",),
        count_keys=("empty_response_count", "empty_count"),
        total_count=total_count,
    )
    zero_token_rate = _quality_rate(
        item,
        rate_keys=("zero_token_rate",),
        count_keys=("zero_token_count",),
        total_count=total_count,
    )
    progress_only_rate = _quality_rate(
        item,
        rate_keys=("progress_only_rate",),
        count_keys=("progress_only_count",),
        total_count=total_count,
    )
    verifier_rejection_rate = _quality_rate(
        item,
        rate_keys=("verifier_rejection_rate",),
        count_keys=("verifier_rejection_count",),
        total_count=total_count,
    )
    output_shape_valid = _quality_bool(item, "output_shape_valid")
    min_accepted = _setting_int(
        "llm_warm_policy_min_accepted_count", 1, minimum=0, maximum=1000
    )
    max_timeout_rate = _setting_float(
        "llm_warm_policy_max_timeout_rate", 0.25, minimum=0.0, maximum=1.0
    )
    max_progress_only_rate = _setting_float(
        "llm_warm_policy_max_progress_only_rate", 0.10, minimum=0.0, maximum=1.0
    )
    max_verifier_rejection_rate = _setting_float(
        "llm_warm_policy_max_verifier_rejection_rate",
        0.30,
        minimum=0.0,
        maximum=1.0,
    )
    reject_zero_token = _setting_bool("llm_warm_policy_reject_zero_token", True)
    reject_empty_response = _setting_bool("llm_warm_policy_reject_empty_response", True)
    metrics = {
        "accepted_count": accepted_count,
        "total_count": total_count,
        "timeout_rate": timeout_rate,
        "empty_response_rate": empty_rate,
        "zero_token_rate": zero_token_rate,
        "progress_only_rate": progress_only_rate,
        "verifier_rejection_rate": verifier_rejection_rate,
        "output_shape_valid": output_shape_valid,
        "min_accepted_count": min_accepted,
        "max_timeout_rate": max_timeout_rate,
        "max_progress_only_rate": max_progress_only_rate,
        "max_verifier_rejection_rate": max_verifier_rejection_rate,
    }

    reason = ""
    state = ""
    if accepted_count is not None and accepted_count < min_accepted:
        state = "accepted_count_low"
        reason = f"accepted_count {accepted_count} below {min_accepted}"
    elif timeout_rate is not None and timeout_rate > max_timeout_rate:
        state = "timeout_heavy"
        reason = f"timeout_rate {timeout_rate:g} above {max_timeout_rate:g}"
    elif reject_empty_response and empty_rate is not None and empty_rate > 0:
        state = "empty_response"
        reason = f"empty_response_rate {empty_rate:g} above 0"
    elif reject_zero_token and zero_token_rate is not None and zero_token_rate > 0:
        state = "zero_token"
        reason = f"zero_token_rate {zero_token_rate:g} above 0"
    elif progress_only_rate is not None and progress_only_rate > max_progress_only_rate:
        state = "progress_only_heavy"
        reason = (
            f"progress_only_rate {progress_only_rate:g} "
            f"above {max_progress_only_rate:g}"
        )
    elif (
        verifier_rejection_rate is not None
        and verifier_rejection_rate > max_verifier_rejection_rate
    ):
        state = "verifier_rejected"
        reason = (
            f"verifier_rejection_rate {verifier_rejection_rate:g} "
            f"above {max_verifier_rejection_rate:g}"
        )
    elif output_shape_valid is False:
        state = "output_shape_invalid"
        reason = "benchmark output shape was invalid"

    if not reason:
        return None
    return {
        "eligible": False,
        "state": state,
        "reason": reason,
        "score": score,
        "coverage_ratio": coverage,
        "min_score": min_score,
        "min_coverage_ratio": min_coverage,
        "quality_metrics": metrics,
        "source": _clean(item.get("source")),
    }


def _benchmark_quality(item: dict[str, Any]) -> dict[str, Any]:
    source = _clean(item.get("source"))
    status = _clean(item.get("benchmark_status")).lower()
    score = _as_float(item.get("score"))
    coverage = _as_float(item.get("coverage_ratio"))
    min_score = _setting_float(
        "llm_warm_policy_min_benchmark_score", 0.6, minimum=0.0, maximum=10.0
    )
    min_coverage = _setting_float(
        "llm_warm_policy_min_coverage_ratio", 0.5, minimum=0.0, maximum=1.0
    )
    if status in BAD_BENCHMARK_STATUSES:
        return {
            "eligible": False,
            "state": "rejected",
            "reason": f"benchmark status {status}",
            "score": score,
            "coverage_ratio": coverage,
            "min_score": min_score,
            "min_coverage_ratio": min_coverage,
            "source": source,
        }
    if source == "uplink_benchmark":
        quality_rejection = _benchmark_quality_rejection(
            item,
            score=score,
            coverage=coverage,
            min_score=min_score,
            min_coverage=min_coverage,
        )
        if quality_rejection:
            return quality_rejection
        if score is not None and score < min_score:
            return {
                "eligible": False,
                "state": "low_score",
                "reason": f"score {score:g} below {min_score:g}",
                "score": score,
                "coverage_ratio": coverage,
                "min_score": min_score,
                "min_coverage_ratio": min_coverage,
                "source": source,
            }
        if coverage is not None and coverage < min_coverage:
            return {
                "eligible": False,
                "state": "low_coverage",
                "reason": f"coverage {coverage:g} below {min_coverage:g}",
                "score": score,
                "coverage_ratio": coverage,
                "min_score": min_score,
                "min_coverage_ratio": min_coverage,
                "source": source,
            }
        if score is None and coverage is None and status not in GOOD_BENCHMARK_STATUSES:
            return {
                "eligible": False,
                "state": "unscored",
                "reason": "benchmark packet did not provide a score",
                "score": score,
                "coverage_ratio": coverage,
                "min_score": min_score,
                "min_coverage_ratio": min_coverage,
                "source": source,
            }
        return {
            "eligible": True,
            "state": status or "benchmark_backed",
            "reason": "benchmark-backed",
            "score": score,
            "coverage_ratio": coverage,
            "min_score": min_score,
            "min_coverage_ratio": min_coverage,
            "quality_metrics": (
                item.get("quality_metrics")
                if isinstance(item.get("quality_metrics"), dict)
                else {}
            ),
            "source": source,
        }
    if source == "capability_catalog":
        return {
            "eligible": False,
            "state": status or "catalog_unproven",
            "reason": "catalog-only model lacks live benchmark proof",
            "score": score,
            "coverage_ratio": coverage,
            "min_score": min_score,
            "min_coverage_ratio": min_coverage,
            "source": source,
        }
    fallback_prefetch = _setting_bool("llm_warm_policy_fallback_prefetch", False)
    priority = _clean(item.get("priority"))
    model_size = _model_size_b(_clean(item.get("model")))
    canary = priority == "canary" or (
        model_size is not None and model_size <= SMALL_MODEL_MAX_B
    )
    return {
        "eligible": bool(fallback_prefetch or canary),
        "state": "fallback_canary" if canary else "fallback_observe",
        "reason": "fallback recommendation"
        if fallback_prefetch
        else "fallback observe",
        "score": score,
        "coverage_ratio": coverage,
        "min_score": min_score,
        "min_coverage_ratio": min_coverage,
        "source": source,
    }


def _recommendation_lanes(item: dict[str, Any]) -> list[str]:
    model = _clean(item.get("model"))
    family = _model_family(model)
    size_b = _model_size_b(model)
    capability_class = _clean(item.get("capability_class")).lower()
    text = " ".join(
        _clean(item.get(key)).lower()
        for key in (
            "profile",
            "use_for",
            "guardrail",
            "contract_id",
            "lane_id",
            "benchmark_status",
            "capability",
            "capability_class",
        )
    )
    lanes: set[str] = set()
    explicit_lane = _clean(item.get("lane_id")).lower()
    explicit_route_lane = explicit_lane in ROUTE_GUARDRAIL_LANES
    class_lanes = {
        "code": "coder",
        "judge": "judge",
        "embed": "embedding",
        "rerank": "rerank",
        "safety": "safety",
        "prompt_injection": "prompt_injection",
        "ocr": "ocr",
        "doc_parse": "doc_parse",
        "gui_ground": "gui_ground",
        "asr": "speech",
        "tts": "speech",
        "forecast": "forecast",
        "graph": "graph",
        "network": "network",
        "vl_embed": "doc_parse",
        "vl_rerank": "doc_parse",
        "world": "world",
    }
    class_lane = class_lanes.get(capability_class, "")
    if explicit_route_lane:
        lanes.add(explicit_lane)
    if class_lane:
        lanes.add(class_lane)
    narrow_specialist = bool(
        (explicit_route_lane and explicit_lane in NARROW_SPECIALIST_LANES)
        or class_lane in NARROW_SPECIALIST_LANES
    )
    if not narrow_specialist:
        for lane, markers in LANE_TEXT_MARKERS.items():
            if any(marker in text for marker in markers):
                lanes.add(lane)
    if not explicit_route_lane and not narrow_specialist:
        lanes.update(LANE_FAMILY_DEFAULTS.get(family, LANE_FAMILY_DEFAULTS["general"]))
    if _clean(item.get("priority")) == "canary" or (
        size_b is not None and size_b <= SMALL_MODEL_MAX_B
    ):
        lanes.add("canary")
        lanes.discard("verifier")
        lanes.discard("coder")
    return [lane for lane in ROUTE_GUARDRAIL_LANES if lane in lanes]


def _route_guardrail(
    item: dict[str, Any],
    quality: dict[str, Any],
    *,
    cooldown: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model = _clean(item.get("model"))
    lanes = _recommendation_lanes(item)
    size_b = _model_size_b(model)
    canary = "canary" in lanes or _clean(item.get("priority")) == "canary"
    active_cooldown = isinstance(cooldown, dict) and bool(cooldown.get("active"))
    if active_cooldown:
        authority = "blocked"
        route_state = "cooldown"
    elif not quality.get("eligible"):
        authority = "blocked"
        route_state = "benchmark_blocked"
    elif canary or (size_b is not None and size_b <= SMALL_MODEL_MAX_B):
        authority = "canary_only"
        route_state = "canary"
    else:
        authority = "preflight_or_draft"
        route_state = "eligible"
    return {
        "schema": "norman.norllama.route-guardrail.v1",
        "lanes": lanes,
        "authority": authority,
        "route_state": route_state,
        "final_authority": False,
        "requires_verification": authority != "blocked",
        "cloud_escalation_required_for": [
            "workspace mutation",
            "external writes",
            "secret access",
            "billing/provider changes",
            "final authority",
        ],
        "reason": _clean(cooldown.get("reason") if active_cooldown else "")
        or _clean(quality.get("reason")),
        "cooldown": dict(cooldown or {}),
    }


def _route_guardrail_matrix(evaluated: list[dict[str, Any]]) -> dict[str, Any]:
    lanes: dict[str, dict[str, Any]] = {
        lane: {
            "lane": lane,
            "eligible_models": [],
            "blocked_models": [],
            "canary_models": [],
        }
        for lane in ROUTE_GUARDRAIL_LANES
    }
    for item in evaluated:
        model = _clean(item.get("model"))
        guardrail = (
            item.get("route_guardrail")
            if isinstance(item.get("route_guardrail"), dict)
            else {}
        )
        authority = _clean(guardrail.get("authority")) or "blocked"
        for lane in guardrail.get("lanes") or []:
            if lane not in lanes or not model:
                continue
            entry = {
                "model": model,
                "action": _clean(item.get("action")),
                "priority": _clean(item.get("priority")),
                "target_worker": _clean(item.get("target_worker")),
                "target_endpoint": _clean(item.get("target_endpoint")),
                "benchmark_quality": item.get("benchmark_quality")
                if isinstance(item.get("benchmark_quality"), dict)
                else {},
                "authority": authority,
            }
            if authority == "blocked":
                lanes[lane]["blocked_models"].append(entry)
            elif authority == "canary_only":
                lanes[lane]["canary_models"].append(entry)
            else:
                lanes[lane]["eligible_models"].append(entry)
    for lane in lanes.values():
        lane["eligible_count"] = len(lane["eligible_models"])
        lane["blocked_count"] = len(lane["blocked_models"])
        lane["canary_count"] = len(lane["canary_models"])
        lane["status"] = (
            "ready"
            if lane["eligible_models"]
            else "canary"
            if lane["canary_models"]
            else "blocked"
        )
    return {
        "schema": "norman.norllama.route-guardrail-matrix.v1",
        "lanes": lanes,
        "lane_order": list(ROUTE_GUARDRAIL_LANES),
        "policy": {
            "local_models_are_advisory": True,
            "final_authority_requires_verified_runtime": True,
            "canary_models_are_health_only": True,
        },
    }


def _candidate_workers(
    workers: list[dict[str, Any]],
    model: str,
    *,
    reachable_only: bool = False,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for worker in workers:
        if reachable_only and not worker.get("reachable"):
            continue
        if _worker_has_model(worker, model):
            result.append(worker)
    return result


def _worker_matches_requested_role(worker: dict[str, Any], role: str) -> bool:
    clean_role = _clean(role).lower()
    if not clean_role:
        return True
    worker_role = _worker_role(worker)
    return clean_role == worker_role or clean_role in worker_role


def _preferred_worker(
    item: dict[str, Any],
    workers: list[dict[str, Any]],
) -> dict[str, Any] | None:
    model = _clean(item.get("model"))
    if not model:
        return None
    candidates = _candidate_workers(workers, model)
    if not candidates:
        return None
    hinted = _clean(item.get("target_worker"))
    if hinted:
        for worker in candidates:
            if _clean(worker.get("id")) == hinted:
                pressure = _worker_pressure(worker)
                if worker.get("reachable") and _clean(pressure.get("state")) != "high":
                    return worker
                break
    hinted_role = _clean(item.get("target_role"))
    if hinted_role:
        role_matches = [
            worker
            for worker in candidates
            if _worker_matches_requested_role(worker, hinted_role)
        ]
        if role_matches:
            candidates = role_matches
    size_b = _model_size_b(model)
    family = _model_family(model)
    active_candidates = [
        worker
        for worker in candidates
        if worker.get("reachable")
        and _worker_active_model(worker, model)
        and _clean(_worker_pressure(worker).get("state")) != "high"
    ]
    if active_candidates:
        return sorted(
            active_candidates,
            key=lambda worker: (
                _worker_pressure(worker).get("active_model_count", 0),
                worker.get("priority", 99),
            ),
        )[0]
    production = [
        worker for worker in candidates if _worker_role(worker) == "production"
    ]
    fallback = [worker for worker in candidates if _worker_role(worker) == "fallback"]
    if (
        size_b is not None
        and size_b <= SMALL_MODEL_MAX_B
        and _clean(item.get("priority")) == "canary"
    ):
        return sorted(
            fallback or candidates,
            key=lambda worker: (
                not bool(worker.get("reachable")),
                worker.get("priority", 99),
            ),
        )[0]
    if production:
        family_preference = {
            "deepseek": "spark-150",
            "qwen": "spark-150",
            "gemma": "spark-151",
            "openfugu": "spark-151",
        }.get(family)
        if family_preference:
            for worker in production:
                if (
                    _clean(worker.get("id")) == family_preference
                    and worker.get("reachable")
                    and _clean(_worker_pressure(worker).get("state")) != "high"
                ):
                    return worker
        return sorted(
            production,
            key=lambda worker: (
                not bool(worker.get("reachable")),
                1 if _clean(_worker_pressure(worker).get("state")) == "high" else 0,
                _worker_pressure(worker).get("active_model_count", 0),
                worker.get("priority", 99),
            ),
        )[0]
    return sorted(
        candidates,
        key=lambda worker: (
            not bool(worker.get("reachable")),
            worker.get("priority", 99),
        ),
    )[0]


def _active_worker_ids(workers: list[dict[str, Any]], model: str) -> list[str]:
    ids: list[str] = []
    for worker in workers:
        if _worker_active_model(worker, model):
            worker_id = _clean(worker.get("id"))
            if worker_id:
                ids.append(worker_id)
    return ids


def _route_outcome_stats(
    outcomes: list[dict[str, Any]] | None,
    *,
    model: str,
    worker_id: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    clean_model = _clean(model)
    clean_worker = _clean(worker_id)
    filtered: list[dict[str, Any]] = []
    for raw in reversed(list(outcomes or [])):
        outcome = normalize_route_outcome(raw)
        if outcome.get("model") != clean_model:
            continue
        if clean_worker and outcome.get("worker_id") not in {"", clean_worker}:
            continue
        filtered.append(outcome)
        if len(filtered) >= max(1, int(limit or 20)):
            break
    if not filtered:
        return {
            "schema": "norman.norllama.route-outcome-stats.v1",
            "count": 0,
            "ok": 0,
            "fail": 0,
            "timeout": 0,
            "success_rate": 0.0,
            "avg_latency_ms": 0,
            "last_status": "",
            "last_worker_id": clean_worker,
        }
    ok = sum(1 for outcome in filtered if outcome.get("ok"))
    fail = len(filtered) - ok
    timeout = sum(
        1 for outcome in filtered if _clean(outcome.get("status")) == "timeout"
    )
    latencies = [
        int(outcome.get("latency_ms") or 0)
        for outcome in filtered
        if int(outcome.get("latency_ms") or 0) > 0
    ]
    return {
        "schema": "norman.norllama.route-outcome-stats.v1",
        "count": len(filtered),
        "ok": ok,
        "fail": fail,
        "timeout": timeout,
        "success_rate": round(ok / len(filtered), 3),
        "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
        "last_status": _clean(filtered[0].get("status")),
        "last_worker_id": _clean(filtered[0].get("worker_id")) or clean_worker,
    }


def _action_for_recommendation(
    item: dict[str, Any],
    *,
    mesh: dict[str, Any],
    workers: list[dict[str, Any]],
    available_models: list[str],
    active_models: list[str],
    enabled: bool,
    route_outcomes: list[dict[str, Any]] | None = None,
    cooldown_seconds: int = 900,
) -> dict[str, Any]:
    model = _clean(item.get("model"))
    quality = _benchmark_quality(item)
    service_evidence, service_workers = _service_workers(
        item=item,
        mesh=mesh,
        workers=workers,
    )
    available = _model_matches(model, available_models) or bool(
        service_evidence.get("installed")
    )
    active = _model_matches(model, active_models)
    model_workers = _candidate_workers(workers, model)
    healthy_model_workers = _candidate_workers(workers, model, reachable_only=True)
    if service_evidence.get("installed"):
        if not model_workers:
            model_workers = service_workers
        if not healthy_model_workers:
            healthy_model_workers = [
                worker for worker in service_workers if worker.get("reachable")
            ]
        if service_evidence.get("resident"):
            active = True
    target_worker = _preferred_worker(item, workers)
    if target_worker is None and service_evidence.get("installed") and service_workers:
        hinted_worker = _clean(item.get("target_worker"))
        if hinted_worker:
            target_worker = next(
                (
                    worker
                    for worker in service_workers
                    if _clean(worker.get("id") or worker.get("worker_id"))
                    == hinted_worker
                ),
                None,
            )
        if target_worker is None:
            target_worker = next(
                (worker for worker in service_workers if worker.get("reachable")),
                service_workers[0],
            )
    target_worker_id = _clean(
        (target_worker or {}).get("id") or (target_worker or {}).get("worker_id")
    ) or _clean(item.get("target_worker"))
    target_endpoint = _worker_public_endpoint(target_worker or {})
    target_reachable = bool((target_worker or {}).get("reachable"))
    target_active = bool(target_worker and _worker_active_model(target_worker, model))
    active_worker_ids = _active_worker_ids(workers, model)
    target_pressure = _worker_pressure(target_worker or {}) if target_worker else {}
    outcome_stats = _route_outcome_stats(
        route_outcomes or [],
        model=model,
        worker_id=target_worker_id,
    )
    cooldown = local_route_cooldown(
        route_outcomes or [],
        model=model,
        endpoint="",
        worker_id=target_worker_id,
        cooldown_seconds=cooldown_seconds,
    )
    residency_state = "cold"
    pressure_state = _clean(target_pressure.get("state"))
    action_reason = ""
    action = "observe"
    if not available:
        action = "skip_unavailable"
        residency_state = "unavailable"
        action_reason = "model is not advertised by the Norllama mesh"
    elif not quality.get("eligible"):
        action = "skip_quality_gate"
        residency_state = "warm" if active else "cold"
        action_reason = _clean(quality.get("reason")) or "benchmark quality gate"
    elif cooldown.get("active"):
        action = "skip_cooldown"
        residency_state = "degraded" if active else "cold"
        action_reason = f"recent {cooldown.get('status')} for {model}" + (
            f" on {cooldown.get('worker_id')}"
            if _clean(cooldown.get("worker_id"))
            else ""
        )
    elif target_active:
        action = "keep_warm"
        residency_state = "warm"
        action_reason = "model is already resident on selected worker"
    elif not healthy_model_workers:
        action = "wait_for_worker"
        residency_state = "degraded"
        action_reason = "no healthy worker currently advertises the model"
    elif target_worker and not target_reachable:
        action = "wait_for_worker"
        residency_state = "degraded"
        action_reason = f"target worker {target_worker_id} is not reachable"
    elif pressure_state == "high" and _clean(item.get("priority")) != "p0":
        action = "skip_worker_pressure"
        residency_state = "cold"
        action_reason = f"target worker {target_worker_id} is under pressure"
    elif enabled and _clean(item.get("priority")) in {"p0", "p1", "canary"}:
        action = "prefetch"
        residency_state = "warming"
        action_reason = "eligible benchmark-backed model is cold"
    else:
        action = "observe"
        residency_state = "cold"
        action_reason = "warm policy disabled or priority is observe-only"
    return {
        **item,
        "available": available,
        "active": active,
        "target_active": target_active,
        "active_worker_ids": active_worker_ids,
        "action": action,
        "action_reason": action_reason,
        "residency_state": residency_state,
        "benchmark_quality": quality,
        "cooldown": cooldown,
        "route_guardrail": _route_guardrail(item, quality, cooldown=cooldown),
        "model_size_b": _model_size_b(model),
        "model_family": _model_family(model),
        "target_worker": target_worker_id,
        "target_endpoint": target_endpoint,
        "target_worker_reachable": target_reachable,
        "candidate_workers": [_clean(worker.get("id")) for worker in model_workers],
        "healthy_candidate_workers": [
            _clean(worker.get("id")) for worker in healthy_model_workers
        ],
        "worker_pressure": target_pressure,
        "route_outcome_stats": outcome_stats,
        "service_evidence": service_evidence,
    }


def _residency_summary(evaluated: list[dict[str, Any]]) -> dict[str, Any]:
    states = {
        "warm": 0,
        "warming": 0,
        "cold": 0,
        "degraded": 0,
        "unavailable": 0,
    }
    actions: dict[str, int] = {}
    for item in evaluated:
        state = _clean(item.get("residency_state")) or "cold"
        states[state] = states.get(state, 0) + 1
        action = _clean(item.get("action")) or "observe"
        actions[action] = actions.get(action, 0) + 1
    return {
        "states": states,
        "actions": actions,
        "warm": states.get("warm", 0),
        "warming": states.get("warming", 0),
        "cold": states.get("cold", 0),
        "degraded": states.get("degraded", 0),
        "unavailable": states.get("unavailable", 0),
    }


def _apply_model_reality(
    evaluated: list[dict[str, Any]],
    reality: dict[str, Any],
) -> list[dict[str, Any]]:
    by_model = (
        reality.get("by_model") if isinstance(reality.get("by_model"), dict) else {}
    )
    result: list[dict[str, Any]] = []
    for item in evaluated:
        model = _clean(item.get("model"))
        row = dict(by_model.get(model) or {})
        if row:
            item = {**item, "model_reality": row}
        if row and not row.get("route_eligible"):
            action = _clean(item.get("action"))
            if action not in {
                "skip_unavailable",
                "skip_quality_gate",
                "skip_cooldown",
                "wait_for_worker",
            }:
                reason = "; ".join(row.get("reasons") or []) or _clean(
                    row.get("proof_status")
                )
                guardrail = (
                    dict(item.get("route_guardrail"))
                    if isinstance(item.get("route_guardrail"), dict)
                    else {}
                )
                guardrail.update(
                    {
                        "authority": "blocked",
                        "route_state": _clean(row.get("proof_status"))
                        or "model_reality_blocked",
                        "reason": reason,
                        "model_reality": {
                            "state": _clean(row.get("state")),
                            "proof_status": _clean(row.get("proof_status")),
                            "route_eligible": False,
                        },
                    }
                )
                item = {
                    **item,
                    "action": "skip_model_reality",
                    "action_reason": reason,
                    "residency_state": "degraded"
                    if row.get("installed")
                    else "unavailable",
                    "route_guardrail": guardrail,
                }
        result.append(item)
    return result


def _prefetch_response_target_honored(
    response: dict[str, Any],
    *,
    target_worker: str,
    target_endpoint: str,
) -> tuple[bool | None, str, str, str]:
    """Compare Norllama prefetch route evidence against the warm-policy target."""

    response_worker = _clean(
        response.get("worker_id")
        or response.get("selected_worker_id")
        or response.get("target_worker")
    )
    response_upstream = _clean(
        response.get("upstream")
        or response.get("upstream_url")
        or response.get("worker_endpoint")
        or response.get("selected_endpoint")
    )
    response_reason = ""
    target_honored: bool | None = None
    if target_worker and response_worker:
        target_honored = response_worker == target_worker
        if not target_honored:
            response_reason = (
                f"gateway selected worker {response_worker} instead of {target_worker}"
            )
    elif target_endpoint and response_upstream:
        target_honored = _endpoint_key(response_upstream) == _endpoint_key(
            target_endpoint
        )
        if not target_honored:
            response_reason = (
                f"gateway selected upstream {response_upstream} "
                f"instead of {target_endpoint}"
            )
    return target_honored, response_worker, response_upstream, response_reason


def _prefetch_response_status(response: dict[str, Any]) -> str:
    job = response.get("job") if isinstance(response.get("job"), dict) else {}
    return _clean(
        response.get("job_status")
        or job.get("status")
        or response.get("status")
        or response.get("state")
    ).lower()


def _prefetch_response_stale_warm_warning(
    response: dict[str, Any],
    *,
    active_at_policy_build: bool,
) -> str:
    status = _prefetch_response_status(response)
    if status not in {"warm", "keep_warm", "resident"}:
        return ""
    if active_at_policy_build:
        return ""
    job = response.get("job") if isinstance(response.get("job"), dict) else {}
    duplicate_count = _as_int(job.get("duplicate_count")) or _as_int(
        response.get("duplicate_count")
    )
    started = response.get("started")
    if started is False or (duplicate_count is not None and duplicate_count > 0):
        return (
            "gateway reported warm from an existing prefetch job, but the mesh "
            "snapshot did not show the model resident before apply"
        )
    return ""


def _prefetch_candidate_allowed(item: dict[str, Any]) -> bool:
    if _clean(item.get("action")) != "prefetch":
        return False
    if not _clean(item.get("model")) or not _clean(item.get("target_worker")):
        return False
    pressure = (
        item.get("worker_pressure")
        if isinstance(item.get("worker_pressure"), dict)
        else {}
    )
    if _clean(pressure.get("state")) == "high":
        return False
    reality = (
        item.get("model_reality") if isinstance(item.get("model_reality"), dict) else {}
    )
    if reality:
        if reality.get("route_eligible") is False:
            return False
        if reality.get("worker_fit") is False:
            return False
        if reality.get("memory_pressure_ok") is False:
            return False
    guardrail = (
        item.get("route_guardrail")
        if isinstance(item.get("route_guardrail"), dict)
        else {}
    )
    return _clean(guardrail.get("authority")) != "blocked"


def _prefetch_candidates(evaluated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in evaluated:
        if not _prefetch_candidate_allowed(item):
            continue
        model = _clean(item.get("model"))
        target_worker = _clean(item.get("target_worker"))
        key = (model, target_worker)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def build_warm_policy(
    *,
    mesh: dict[str, Any] | None = None,
    packet: dict[str, Any] | None = None,
    route_outcomes: list[dict[str, Any]] | None = None,
    cooldown_seconds: int = 900,
    include_mesh: bool = False,
) -> dict[str, Any]:
    """Build the benchmark-backed local warm model policy."""

    benchmark_meta: dict[str, Any]
    if packet is None:
        packet, benchmark_meta = load_benchmark_packet()
    else:
        benchmark_meta = {
            "status": "provided",
            "source": "provided",
            "packet_id": _clean(packet.get("packet_id") or packet.get("id"))
            or _clean(packet.get("generated_at")),
            "generated_at": _clean(packet.get("generated_at")),
        }
    recommendations = benchmark_recommendations(packet or {}) if packet else []
    if not recommendations:
        recommendations = _fallback_recommendations()
    mesh_payload = mesh or get_mesh_overview(timeout_seconds=2)
    available_models = _public_models_from_mesh(mesh_payload)
    active_models = _active_models_from_mesh(mesh_payload)
    workers = _mesh_workers(mesh_payload)
    enabled = bool(getattr(settings, "llm_warm_policy_enabled", True))
    evaluated: list[dict[str, Any]] = []
    for item in recommendations:
        evaluated.append(
            _action_for_recommendation(
                item,
                mesh=mesh_payload,
                workers=workers,
                available_models=available_models,
                active_models=active_models,
                enabled=enabled,
                route_outcomes=route_outcomes or [],
                cooldown_seconds=cooldown_seconds,
            )
        )
    model_reality = build_model_reality(
        mesh=mesh_payload,
        benchmark_items=evaluated,
        route_outcomes=route_outcomes or [],
        packet_meta=benchmark_meta,
        cooldown_seconds=cooldown_seconds,
    )
    evaluated = _apply_model_reality(evaluated, model_reality)
    prefetch_candidates = _prefetch_candidates(evaluated)
    worker_plan: dict[str, dict[str, Any]] = {
        _clean(worker.get("id")): {
            **_worker_summary(worker),
            "desired_models": [],
            "prefetch_models": [],
        }
        for worker in workers
        if _clean(worker.get("id"))
    }
    prefetch_keys = {
        (_clean(item.get("model")), _clean(item.get("target_worker")))
        for item in prefetch_candidates
    }
    for item in evaluated:
        worker_id = _clean(item.get("target_worker"))
        if not worker_id or worker_id not in worker_plan:
            continue
        worker_plan[worker_id]["desired_models"].append(_clean(item.get("model")))
        if (_clean(item.get("model")), worker_id) in prefetch_keys:
            worker_plan[worker_id]["prefetch_models"].append(_clean(item.get("model")))
    residency = _residency_summary(evaluated)
    p0_routable = [
        item
        for item in evaluated
        if item.get("priority") == "p0"
        and item.get("route_guardrail", {}).get("authority") != "blocked"
    ]
    p0_available = any(item.get("available") for item in p0_routable)
    p0_active = any(
        item.get("active") and item.get("action") != "skip_cooldown"
        for item in p0_routable
    )
    if p0_active:
        route_posture = "ready"
    elif p0_available:
        route_posture = "prefetch_or_wait"
    else:
        route_posture = "fallback_or_cloud_gate"
    payload = {
        "schema": "norman.norllama.warm-policy.v1",
        "enabled": enabled,
        "status": "ok" if available_models else "mesh_unavailable",
        "route_posture": route_posture,
        "residency_posture": "warm"
        if residency["warm"]
        else "warming"
        if residency["warming"]
        else "degraded"
        if residency["degraded"]
        else "cold",
        "benchmark": benchmark_meta,
        "route_outcomes": {
            "provided_count": len(route_outcomes or []),
            "cooldown_seconds": max(0, int(cooldown_seconds or 0)),
            "cooldown_count": sum(
                1 for item in evaluated if item.get("cooldown", {}).get("active")
            ),
        },
        "model_reality": {
            key: value for key, value in model_reality.items() if key != "by_model"
        },
        "capability_catalog": catalog_payload(),
        "frontdoor": {
            "status": _clean((mesh_payload.get("frontdoor") or {}).get("status")),
            "reachable": bool((mesh_payload.get("frontdoor") or {}).get("reachable")),
        },
        "mesh_cache": mesh_payload.get("cache")
        if isinstance(mesh_payload.get("cache"), dict)
        else {},
        "available_model_count": len(available_models),
        "active_model_count": len(active_models),
        "recommendations": evaluated,
        "route_guardrails": _route_guardrail_matrix(evaluated),
        "prefetch_candidates": prefetch_candidates,
        "residency": residency,
        "workers": list(worker_plan.values()),
        "counts": {
            "recommendations": len(evaluated),
            "prefetch": len(prefetch_candidates),
            "keep_warm": sum(
                1 for item in evaluated if item.get("action") == "keep_warm"
            ),
            "skip_unavailable": sum(
                1 for item in evaluated if item.get("action") == "skip_unavailable"
            ),
            "skip_quality_gate": sum(
                1 for item in evaluated if item.get("action") == "skip_quality_gate"
            ),
            "wait_for_worker": sum(
                1 for item in evaluated if item.get("action") == "wait_for_worker"
            ),
            "skip_worker_pressure": sum(
                1 for item in evaluated if item.get("action") == "skip_worker_pressure"
            ),
            "skip_cooldown": sum(
                1 for item in evaluated if item.get("action") == "skip_cooldown"
            ),
            "skip_model_reality": sum(
                1 for item in evaluated if item.get("action") == "skip_model_reality"
            ),
        },
        "checked_at": time.time(),
    }
    if include_mesh:
        payload["mesh"] = mesh_payload
    return payload


def _selection_lanes_for_task_kind(
    kind: str,
    *,
    preferred_lane: str = "",
) -> list[str]:
    lanes: list[str] = []
    if _clean(preferred_lane):
        lanes.append(_clean(preferred_lane))
    for lane in TASK_KIND_ROUTE_LANES.get(_clean(kind).lower(), ("planner",)):
        if lane not in lanes:
            lanes.append(lane)
    return lanes


def _recommendation_selection_rank(
    item: dict[str, Any],
    lane: str,
    lane_index: int,
) -> tuple:
    return (
        lane_index,
        ACTION_SELECTION_RANK.get(_clean(item.get("action")), 9),
        PRIORITY_RANK.get(_clean(item.get("priority")), 9),
        0 if _clean((item.get("target_worker") or "")).startswith("spark") else 1,
        _clean(item.get("model")),
        lane,
    )


def _selection_strategy(policy: dict[str, Any] | None) -> str:
    strategy = _clean(
        (policy or {}).get("pool_strategy")
        or (policy or {}).get("model_pool_strategy")
        or (policy or {}).get("selection_strategy")
    ).lower()
    return strategy if strategy in POOL_STRATEGIES else "balanced"


def _pool_candidate_score(
    item: dict[str, Any],
    *,
    lane: str,
    lane_index: int,
    strategy: str,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 1000.0 - (lane_index * 220.0)
    action = _clean(item.get("action"))
    action_bonus = {"keep_warm": 140.0, "prefetch": 85.0, "observe": 20.0}.get(
        action, 0.0
    )
    score += action_bonus
    if action_bonus:
        reasons.append(action)
    priority = _clean(item.get("priority"))
    score += {"p0": 80.0, "p1": 45.0, "canary": 5.0, "p2": 10.0}.get(priority, 0.0)
    quality = (
        item.get("benchmark_quality")
        if isinstance(item.get("benchmark_quality"), dict)
        else {}
    )
    benchmark_score = (
        _as_float(quality.get("score")) or _as_float(item.get("score")) or 0.0
    )
    coverage = (
        _as_float(quality.get("coverage_ratio"))
        or _as_float(item.get("coverage_ratio"))
        or 0.0
    )
    if strategy == "quality":
        score += benchmark_score * 140.0
        score += coverage * 60.0
    else:
        score += benchmark_score * 75.0
        score += coverage * 35.0
    if benchmark_score:
        reasons.append(f"score={benchmark_score:g}")
    if coverage:
        reasons.append(f"coverage={coverage:g}")
    if item.get("target_active"):
        score += 80.0 if strategy != "quality" else 35.0
        reasons.append("resident")
    elif item.get("active"):
        score += 20.0
        reasons.append("resident_elsewhere")
    if strategy == "resident" and item.get("target_active"):
        score += 120.0
    target_worker = _clean(item.get("target_worker"))
    if target_worker.startswith("spark"):
        score += 28.0
        reasons.append("spark")
    pressure = (
        item.get("worker_pressure")
        if isinstance(item.get("worker_pressure"), dict)
        else {}
    )
    pressure_state = _clean(pressure.get("state"))
    if pressure_state == "high":
        score -= 180.0
        reasons.append("worker_pressure=high")
    elif pressure_state == "low":
        score += 20.0
    score -= min(80.0, float(pressure.get("active_model_count") or 0) * 10.0)
    stats = (
        item.get("route_outcome_stats")
        if isinstance(item.get("route_outcome_stats"), dict)
        else {}
    )
    if stats.get("count"):
        success_rate = float(stats.get("success_rate") or 0.0)
        score += success_rate * 65.0
        failures = int(stats.get("fail") or 0)
        timeouts = int(stats.get("timeout") or 0)
        score -= failures * 35.0
        score -= timeouts * 45.0
        latency = int(stats.get("avg_latency_ms") or 0)
        if latency:
            latency_penalty = min(
                140.0, latency / (45.0 if strategy == "fast" else 80.0)
            )
            score -= latency_penalty
            reasons.append(f"avg_latency_ms={latency}")
        reasons.append(f"recent_success={success_rate:g}")
    if strategy == "fast":
        size_b = item.get("model_size_b")
        if size_b is not None:
            score -= min(120.0, float(size_b) * 2.5)
            reasons.append(f"size_b={size_b:g}")
    return round(score, 3), reasons


def _pool_candidate_entry(
    item: dict[str, Any],
    *,
    lane: str,
    lane_index: int,
    strategy: str,
) -> dict[str, Any]:
    score, reasons = _pool_candidate_score(
        item,
        lane=lane,
        lane_index=lane_index,
        strategy=strategy,
    )
    return {
        "model": _clean(item.get("model")),
        "lane": lane,
        "lane_index": lane_index,
        "score": score,
        "score_reasons": reasons,
        "action": _clean(item.get("action")),
        "priority": _clean(item.get("priority")),
        "target_worker": _clean(item.get("target_worker")),
        "target_endpoint": _clean(item.get("target_endpoint")),
        "target_active": bool(item.get("target_active")),
        "active_worker_ids": item.get("active_worker_ids")
        if isinstance(item.get("active_worker_ids"), list)
        else [],
        "benchmark_quality": item.get("benchmark_quality")
        if isinstance(item.get("benchmark_quality"), dict)
        else {},
        "model_reality": item.get("model_reality")
        if isinstance(item.get("model_reality"), dict)
        else {},
        "route_outcome_stats": item.get("route_outcome_stats")
        if isinstance(item.get("route_outcome_stats"), dict)
        else {},
        "worker_pressure": item.get("worker_pressure")
        if isinstance(item.get("worker_pressure"), dict)
        else {},
    }


def select_model_for_task_kind(
    kind: str,
    *,
    preferred_lane: str = "",
    policy: dict[str, Any] | None = None,
    mesh: dict[str, Any] | None = None,
    packet: dict[str, Any] | None = None,
    route_outcomes: list[dict[str, Any]] | None = None,
    warm_policy_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select a benchmark/warm-policy-backed local model for a task kind."""

    payload = warm_policy_payload or build_warm_policy(
        mesh=mesh,
        packet=packet,
        route_outcomes=route_outcomes or [],
    )
    lanes = _selection_lanes_for_task_kind(
        kind,
        preferred_lane=preferred_lane
        or _clean((policy or {}).get("lane"))
        or _clean((policy or {}).get("preferred_lane")),
    )
    strategy = _selection_strategy(policy)
    lane_presence = {lane: False for lane in lanes}
    candidates: list[tuple[tuple, dict[str, Any], str, dict[str, Any]]] = []
    for item in payload.get("recommendations") or []:
        if not isinstance(item, dict):
            continue
        guardrail = item.get("route_guardrail")
        if not isinstance(guardrail, dict):
            continue
        item_lanes = [str(lane) for lane in guardrail.get("lanes") or []]
        lane_index = -1
        selected_lane = ""
        for index, lane in enumerate(lanes):
            if lane in item_lanes:
                lane_presence[lane] = True
                if not selected_lane:
                    selected_lane = lane
                    lane_index = index
        if not selected_lane:
            continue
        action = _clean(item.get("action"))
        if action not in ACTION_SELECTION_RANK:
            continue
        if not item.get("available"):
            continue
        if _clean(guardrail.get("authority")) == "blocked":
            continue
        pool_entry = _pool_candidate_entry(
            item,
            lane=selected_lane,
            lane_index=lane_index,
            strategy=strategy,
        )
        candidates.append(
            (
                (
                    -float(pool_entry.get("score") or 0.0),
                    *_recommendation_selection_rank(item, selected_lane, lane_index),
                ),
                item,
                selected_lane,
                pool_entry,
            )
        )
    candidates.sort(key=lambda entry: entry[0])
    if (
        lanes
        and lane_presence.get(lanes[0])
        and not any(entry[2] == lanes[0] for entry in candidates)
    ):
        return {
            "schema": "norman.norllama.warm-policy-selection.v1",
            "selected": False,
            "task_kind": _clean(kind),
            "lanes": lanes,
            "reason": f"no eligible warm-policy model for primary lane {lanes[0]}",
            "pool_strategy": strategy,
            "pool": [],
            "warm_policy_status": _clean(payload.get("status")),
            "route_posture": _clean(payload.get("route_posture")),
        }
    if not candidates:
        return {
            "schema": "norman.norllama.warm-policy-selection.v1",
            "selected": False,
            "task_kind": _clean(kind),
            "lanes": lanes,
            "reason": "no eligible warm-policy model for task kind",
            "pool_strategy": strategy,
            "pool": [],
            "warm_policy_status": _clean(payload.get("status")),
            "route_posture": _clean(payload.get("route_posture")),
        }
    _rank, item, selected_lane, selected_pool_entry = candidates[0]
    pool = [entry[3] for entry in candidates[:10]]
    benchmark_meta = (
        payload.get("benchmark") if isinstance(payload.get("benchmark"), dict) else {}
    )
    return {
        "schema": "norman.norllama.warm-policy-selection.v1",
        "selected": True,
        "task_kind": _clean(kind),
        "lane": selected_lane,
        "lanes": lanes,
        "pool_strategy": strategy,
        "pool_size": len(candidates),
        "pool": pool,
        "selected_score": selected_pool_entry.get("score"),
        "score_reasons": selected_pool_entry.get("score_reasons") or [],
        "model": _clean(item.get("model")),
        "action": _clean(item.get("action")),
        "priority": _clean(item.get("priority")),
        "target_worker": _clean(item.get("target_worker")),
        "target_endpoint": _clean(item.get("target_endpoint")),
        "benchmark_packet_id": _clean(
            benchmark_meta.get("packet_id") or benchmark_meta.get("generated_at")
        ),
        "benchmark_fresh": bool(
            _clean(benchmark_meta.get("status")) in {"loaded", "provided"}
        ),
        "benchmark_quality": item.get("benchmark_quality")
        if isinstance(item.get("benchmark_quality"), dict)
        else {},
        "route_guardrail": item.get("route_guardrail")
        if isinstance(item.get("route_guardrail"), dict)
        else {},
        "warm_policy_status": _clean(payload.get("status")),
        "route_posture": _clean(payload.get("route_posture")),
    }


def apply_warm_policy(
    *,
    dry_run: bool = True,
    prefetch_limit: int | None = None,
    priority: str = "background",
) -> dict[str, Any]:
    """Apply the warm policy through bounded Norllama prefetch calls."""

    policy = build_warm_policy()
    limit = (
        int(prefetch_limit)
        if prefetch_limit is not None
        else _setting_int("llm_warm_policy_prefetch_limit", 3, minimum=0, maximum=20)
    )
    timeout = _setting_int(
        "llm_warm_policy_prefetch_timeout_seconds", 30, minimum=1, maximum=120
    )
    candidates = list(policy.get("prefetch_candidates") or [])[:limit]
    results: list[dict[str, Any]] = []
    for item in candidates:
        model = _clean(item.get("model"))
        target_worker = _clean(item.get("target_worker"))
        target_endpoint = _clean(item.get("target_endpoint"))
        active_at_policy_build = bool(item.get("active"))
        if dry_run:
            results.append(
                {
                    "model": model,
                    "status": "planned",
                    "dry_run": True,
                    "priority": priority,
                    "target_worker": target_worker,
                    "target_endpoint": target_endpoint,
                    "residency_confirmed_at_policy_build": active_at_policy_build,
                }
            )
            continue
        try:
            response = gateway.prefetch_model(
                model=model,
                priority=priority,
                source="norman-warm-policy",
                target_worker=target_worker,
                target_endpoint=target_endpoint,
                timeout_seconds=timeout,
            )
            (
                target_honored,
                response_worker,
                response_upstream,
                target_mismatch,
            ) = _prefetch_response_target_honored(
                response,
                target_worker=target_worker,
                target_endpoint=target_endpoint,
            )
            residency_warning = _prefetch_response_stale_warm_warning(
                response,
                active_at_policy_build=active_at_policy_build,
            )
            results.append(
                {
                    "model": model,
                    "status": _clean(response.get("status")) or "accepted",
                    "ok": bool(response.get("ok", True)),
                    "dry_run": False,
                    "priority": priority,
                    "target_worker": target_worker,
                    "target_endpoint": target_endpoint,
                    "target_honored": target_honored,
                    "response_worker": response_worker,
                    "response_upstream": response_upstream,
                    "target_mismatch": target_mismatch,
                    "residency_confirmed_at_policy_build": active_at_policy_build,
                    "residency_warning": residency_warning,
                    "job_id": _clean(response.get("job_id")),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "model": model,
                    "status": "error",
                    "ok": False,
                    "dry_run": False,
                    "priority": priority,
                    "error": _clean(exc)[:240],
                }
            )
    return {
        "schema": "norman.norllama.warm-apply.v1",
        "dry_run": dry_run,
        "prefetch_limit": limit,
        "attempted": len(results),
        "results": results,
        "policy": policy,
        "checked_at": time.time(),
    }
