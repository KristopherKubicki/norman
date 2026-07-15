#!/usr/bin/env python3
"""Map live local model inventory onto the existing skill-routing matrix."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any


SCHEMA = "norman.local-model-skill-floor.v1"
DEFAULT_OLLAMA_SENSE_JSON = Path("tmp/ollama_sense_live.json")
DEFAULT_VLLM_SENSE_JSON = Path("tmp/vllm_sense_live.json")
DEFAULT_NORLLAMA_CAPABILITIES_JSON = Path("tmp/norllama_capabilities_live.json")
DEFAULT_NORLLAMA_BENCHMARK_PACKET_JSON = Path(
    "scripts/norllama/evidence/norllama_route_proof_benchmark_packet_latest/packet.json"
)
DEFAULT_SKILL_MATRIX_JSON = Path("tmp/work_domain_skill_matrix.json")
DEFAULT_OUTPUT_JSON = Path("tmp/local_model_skill_floors.json")
DEFAULT_OUTPUT_MD = Path("tmp/local_model_skill_floors.md")

TIER_REQUIRED_CAPACITY = {
    "local_no_model": 0,
    "small_bedrock_worker": 2,
    "medium_bedrock_worker": 3,
    "bedrock_gpt_5_4_xhigh_verifier": 3,
    "bedrock_gpt_5_5_xhigh_final": 4,
}
NON_TEXT_MODEL_NEEDLES = (
    "whisper",
    "embed",
    "embedding",
    "nomic",
    "bge",
    "minilm",
    "clip",
    "rerank",
    "tts",
    "stt",
)


@dataclass(frozen=True)
class LocalModel:
    endpoint: str
    model: str
    capacity_rank: int
    family: str
    provider: str
    source_schema: str
    endpoint_scope: str
    runtime_class: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LowModelTrialProfile:
    id: str
    label: str
    model: str
    provider: str
    capacity_rank: int
    family: str
    lane: str
    max_autonomy_level: int
    try_now: bool
    allowed_use: str
    not_allowed_use: str
    promotion_gate: str
    live_inventory_profile: bool = False
    runtime_provider: str = ""
    runtime_class: str = ""
    endpoint: str = ""
    source_schema: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


LOW_MODEL_TRIAL_PROFILES = (
    LowModelTrialProfile(
        id="deterministic_no_model",
        label="Deterministic no-model lane",
        model="local-tools",
        provider="local",
        capacity_rank=0,
        family="deterministic",
        lane="local_first",
        max_autonomy_level=0,
        try_now=True,
        allowed_use="status reads, exact counts, JSON normalization, deterministic diffs",
        not_allowed_use="semantic synthesis, final answers, or external writes",
        promotion_gate="Local result must include source artifact refs and exact command evidence.",
    ),
    LowModelTrialProfile(
        id="tiny_local_text_1b_4b",
        label="Tiny local text 1B-4B",
        model="llama3.2:1b or gemma3:4b",
        provider="ollama",
        capacity_rank=1,
        family="tiny_text_worker",
        lane="contract_only_worker",
        max_autonomy_level=1,
        try_now=True,
        allowed_use="strict JSON rewrites, label cleanup, checklist expansion",
        not_allowed_use="tool use, code edits, evidence adjudication, or operator-facing final replies",
        promotion_gate=">=98% strict JSON on contract-only cases with no invented fields.",
    ),
    LowModelTrialProfile(
        id="small_local_text_8b_20b",
        label="Small local text 8B-20B",
        model="qwen3:8b or gpt-oss:20b",
        provider="ollama/vllm",
        capacity_rank=2,
        family="small_local_worker",
        lane="readonly_scout_worker",
        max_autonomy_level=2,
        try_now=True,
        allowed_use="read-only extraction, clustering, triage cards, bounded evidence summaries",
        not_allowed_use="live mutation, broad repo search, unverified final conclusions",
        promotion_gate="5.4 verifier rejects <5% of sampled scout outputs over 50 receipts.",
    ),
    LowModelTrialProfile(
        id="gpt_5_4_mini_worker",
        label="GPT-5.4 Mini worker",
        model="gpt-5.4-mini",
        provider="openai",
        capacity_rank=2,
        family="cheap_cloud_worker",
        lane="mini_worker",
        max_autonomy_level=2,
        try_now=True,
        allowed_use="bounded background drafts, small patch plans, strict JSON worker output",
        not_allowed_use="claiming tests passed, applying patches directly, live mutation, or final authority",
        promotion_gate="strict JSON plus verifier acceptance; no allowed-files drift in patch-plan cases.",
    ),
    LowModelTrialProfile(
        id="local_coder_30b",
        label="Local coder 30B class",
        model="qwen3-coder:30b or coder-next",
        provider="ollama/vllm",
        capacity_rank=3,
        family="coder",
        lane="coder_scout",
        max_autonomy_level=2,
        try_now=True,
        allowed_use="known-file code review, patch sketches, test-list expansion",
        not_allowed_use="working-tree writes or shell execution without a broker and verifier",
        promotion_gate="zero file-scope drift; required tests named; 5.4 verifier accepts patch sketch.",
    ),
    LowModelTrialProfile(
        id="bedrock_low_cost_coder_scout",
        label="Bedrock low-cost coder/scout",
        model="qwen3-coder-30b, kimi-k2.5, ministral-14b",
        provider="aws-bedrock",
        capacity_rank=3,
        family="bedrock_scout",
        lane="bedrock_coder_scout",
        max_autonomy_level=2,
        try_now=True,
        allowed_use="second opinions, runbook triage, bounded patch review",
        not_allowed_use="direct TUI authority, live writes, or unpriced broad loops",
        promotion_gate="route smoke passes; strict JSON stable; invoice/cost status is known or explicitly marked unknown.",
    ),
    LowModelTrialProfile(
        id="frontier_local_shadow_120b",
        label="Frontier-size local shadow",
        model="qwen3.5:122b or gpt-oss:120b",
        provider="local/vllm",
        capacity_rank=4,
        family="frontier_local_shadow",
        lane="frontier_shadow",
        max_autonomy_level=2,
        try_now=False,
        allowed_use="shadow review, disagreement analysis, high-context draft synthesis",
        not_allowed_use="approval-gated live action or replacing 5.5 final authority",
        promotion_gate="shadow disagreements must catch real defects without adding operator noise.",
    ),
)

TRY_NOW_STATUSES = {
    "contract_only_candidate",
    "try_now_low_risk_candidate",
    "worker_with_5_4_verifier",
    "validator_bounded_final_candidate",
}
CAPABILITY_STATUSES = TRY_NOW_STATUSES | {"deterministic_match"}


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _model_capacity(model: str) -> tuple[int, str]:
    name = _norm(model)
    if not name:
        return 0, "unknown"
    if any(needle in name for needle in NON_TEXT_MODEL_NEEDLES):
        return 0, "non_text"
    if "llama3.2:1b" in name or re.search(r"(^|:)1b\b", name):
        return 1, "tiny"
    if (
        "vision" in name
        or "minicpm" in name
        or re.search(r"(^|[-.:])vl\b", name)
        or re.search(r"qwen[\w.:-]*vl", name)
    ):
        return 2, "vision_local_worker"
    if "qwen3:8b" in name or re.search(r"(^|:)8b\b", name):
        return 2, "small_local_worker"
    if "gemma3:4b" in name or re.search(r"(^|:)4b\b", name):
        return 1, "tiny_text_worker"
    if "coder-next" in name:
        return 3, "coder"
    if "coder" in name and "35b" in name:
        return 3, "coder"
    if "coder" in name and "30b" in name:
        return 2, "coder"
    if "27b" in name:
        return 3, "large_local_worker"
    if "gpt-oss:20b" in name or "30b" in name:
        return 2, "small_local_worker"
    if any(token in name for token in ("120b", "122b", "235b")):
        return 4, "frontier_local_shadow"
    if "35b" in name:
        return 3, "large_local_worker"
    return 0, "unknown_unranked"


def _sense_provider(report: dict[str, Any], endpoint: dict[str, Any]) -> str:
    schema = _norm(report.get("schema"))
    raw_provider = _norm(endpoint.get("provider") or report.get("provider"))
    endpoint_url = _norm(endpoint.get("endpoint"))
    if "vllm" in raw_provider or "vllm" in schema:
        return "vllm"
    if "ollama" in raw_provider or "ollama" in schema:
        return "ollama"
    if ":11434" in endpoint_url:
        return "ollama"
    if ":8000" in endpoint_url:
        return "vllm"
    if raw_provider:
        return raw_provider.replace(" ", "_")
    return "local"


def _runtime_class(provider: str, endpoint_url: str, model: str) -> str:
    label = _norm(f"{provider} {endpoint_url} {model}")
    if provider == "vllm" or "vllm" in label or "spark" in label:
        return "spark_vllm"
    if provider == "ollama":
        return "ollama"
    return "local"


def _offline_priority(item: LocalModel) -> int:
    if item.runtime_class == "spark_vllm":
        return 0
    if item.provider == "ollama":
        return 1
    return 2


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_json(path: Path) -> dict[str, Any]:
    try:
        return load_json(path)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def local_model_inventory(*sense_reports: dict[str, Any]) -> list[LocalModel]:
    models: list[LocalModel] = []
    for report in sense_reports:
        if not isinstance(report, dict):
            continue
        for endpoint in report.get("endpoints") or []:
            if not isinstance(endpoint, dict) or not endpoint.get("ok"):
                continue
            endpoint_url = str(endpoint.get("endpoint") or "").strip()
            provider = _sense_provider(report, endpoint)
            source_schema = str(report.get("schema") or "")
            endpoint_scope = str(endpoint.get("scope") or "")
            for model in endpoint.get("models") or []:
                model_name = str(model or "").strip()
                if not endpoint_url or not model_name:
                    continue
                capacity_rank, family = _model_capacity(model_name)
                models.append(
                    LocalModel(
                        endpoint=endpoint_url,
                        model=model_name,
                        capacity_rank=capacity_rank,
                        family=family,
                        provider=provider,
                        source_schema=source_schema,
                        endpoint_scope=endpoint_scope,
                        runtime_class=_runtime_class(
                            provider, endpoint_url, model_name
                        ),
                    )
                )
    return sorted(
        models,
        key=lambda item: (
            item.capacity_rank,
            0 if "coder" in item.family else 1,
            _offline_priority(item),
            item.model,
            item.endpoint,
        ),
    )


def norllama_capabilities_as_sense_report(report: dict[str, Any]) -> dict[str, Any]:
    """Normalize Norllama capability/model inventory into the existing sense shape."""

    if not isinstance(report, dict):
        return {}
    models: set[str] = set()

    def visit(value: Any, *, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, key=str(child_key))
            return
        if isinstance(value, list):
            for item in value:
                visit(item, key=key)
            return
        if key in {"model", "model_name", "runtime_model"}:
            model = str(value or "").strip()
            if model:
                models.add(model)

    visit(report)
    endpoint = str(
        report.get("frontdoor") or report.get("endpoint") or "https://llm.home.arpa"
    ).strip()
    if not models:
        return {}
    return {
        "schema": "norman.norllama-capabilities-sense.v1",
        "provider": "norllama",
        "endpoints": [
            {
                "endpoint": endpoint,
                "ok": True,
                "scope": "norllama_live_inventory",
                "models": sorted(models),
            }
        ],
    }


def benchmark_packet_model_states(packet: dict[str, Any]) -> dict[str, str]:
    states: dict[str, str] = {}

    def maybe_add(row: dict[str, Any]) -> None:
        model = str(
            row.get("model")
            or row.get("runtime_model")
            or row.get("requested_model")
            or row.get("selected_model")
            or ""
        ).strip()
        if not model:
            return
        state = str(
            row.get("benchmark_status") or row.get("status") or row.get("state") or ""
        ).strip()
        if state:
            states[model] = state

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            maybe_add(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    if isinstance(packet, dict):
        visit(packet)
    return dict(sorted(states.items()))


def _requires_final_authority(row: dict[str, Any]) -> bool:
    decision = row.get("model_routing_decision")
    if not isinstance(decision, dict):
        decision = {}
    return bool(
        row.get("final_authority_required")
        or row.get("requires_high_authority")
        or row.get("requires_state_change")
        or decision.get("requires_5_5_final")
        or str(decision.get("minimum_model_tier") or "")
        == "bedrock_gpt_5_5_xhigh_final"
    )


def _select_local_model(
    inventory: list[LocalModel],
    *,
    required_capacity: int,
    prefer_code: bool,
    prefer_vision: bool,
) -> LocalModel | None:
    candidates = _eligible_local_candidates(
        inventory,
        required_capacity=required_capacity,
        prefer_vision=prefer_vision,
    )
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            item.capacity_rank,
            0 if prefer_code and item.family == "coder" else 1,
            0 if prefer_vision and item.family == "vision_local_worker" else 1,
            _offline_priority(item),
            item.model,
            item.endpoint,
        ),
    )[0]


def _eligible_local_candidates(
    inventory: list[LocalModel],
    *,
    required_capacity: int,
    prefer_vision: bool,
) -> list[LocalModel]:
    if required_capacity <= 0:
        return []
    candidates = [item for item in inventory if item.capacity_rank >= required_capacity]
    if not candidates:
        return []
    if not prefer_vision:
        text_candidates = [
            item for item in candidates if item.family != "vision_local_worker"
        ]
        if text_candidates:
            candidates = text_candidates
    return candidates


def floor_for_skill(
    row: dict[str, Any],
    inventory: list[LocalModel],
    *,
    benchmark_model_states: dict[str, str] | None = None,
) -> dict[str, Any]:
    decision = row.get("model_routing_decision")
    if not isinstance(decision, dict):
        decision = {}
    readiness = row.get("lower_model_readiness")
    if not isinstance(readiness, dict):
        readiness = {}
    minimum_tier = str(
        decision.get("minimum_model_tier")
        or row.get("minimum_matrix_tier")
        or "unknown"
    )
    required_capacity = TIER_REQUIRED_CAPACITY.get(minimum_tier, 3)
    final_authority_required = _requires_final_authority(row)
    family = str(row.get("family") or "")
    label = str(row.get("label") or "")
    prefer_code = family == "code"
    prefer_vision = any(
        token in f"{family} {label}".lower()
        for token in ("vision", "visual", "image", "screenshot")
    )
    selected = _select_local_model(
        inventory,
        required_capacity=required_capacity,
        prefer_code=prefer_code,
        prefer_vision=prefer_vision,
    )
    candidates = _eligible_local_candidates(
        inventory,
        required_capacity=required_capacity,
        prefer_vision=prefer_vision,
    )
    benchmark_states = benchmark_model_states or {}
    selected_benchmark_state = benchmark_states.get(selected.model) if selected else ""
    spark_vllm_candidate_count = sum(
        1 for item in candidates if item.runtime_class == "spark_vllm"
    )
    ollama_candidate_count = sum(1 for item in candidates if item.provider == "ollama")
    if required_capacity <= 0:
        offline_optimizer_state = "deterministic_no_model"
    elif selected is None:
        offline_optimizer_state = "cloud_required_no_local_candidate"
    elif selected.runtime_class == "spark_vllm":
        offline_optimizer_state = "spark_vllm_selected"
    elif spark_vllm_candidate_count:
        offline_optimizer_state = "local_selected_with_spark_vllm_available"
    elif selected.provider == "ollama":
        offline_optimizer_state = "ollama_fallback_no_usable_spark_vllm"
    else:
        offline_optimizer_state = "local_fallback_other_runtime"
    if required_capacity <= 0:
        status = "local_no_model"
        role = "deterministic_only"
    elif selected is None:
        status = "no_local_candidate"
        role = "fallback_to_bedrock"
    elif final_authority_required:
        status = "local_draft_only_final_authority_hold"
        role = "draft_only"
    elif bool(readiness.get("can_shadow_roll_out_lower_final")) and bool(
        readiness.get("has_deterministic_validator")
    ):
        status = "local_validator_bounded_final_candidate"
        role = "validator_bounded_final_candidate"
    elif bool(decision.get("requires_5_4_verifier")):
        status = "local_worker_with_bedrock_5_4_verifier"
        role = "worker_draft"
    else:
        status = "local_shadow_only"
        role = "shadow_only"
    return {
        "skill_id": row.get("skill_id"),
        "domain": row.get("domain"),
        "family": row.get("family"),
        "label": row.get("label"),
        "requires_tools": bool(row.get("requires_tools")),
        "requires_code": bool(row.get("requires_code")),
        "requires_state_change": bool(row.get("requires_state_change")),
        "requires_high_authority": bool(row.get("requires_high_authority")),
        "minimum_matrix_tier": minimum_tier,
        "required_local_capacity_rank": required_capacity,
        "local_floor_status": status,
        "allowed_role": role,
        "selected_local_model": selected.model if selected else "",
        "selected_local_endpoint": selected.endpoint if selected else "",
        "selected_local_model_family": selected.family if selected else "",
        "selected_local_capacity_rank": selected.capacity_rank if selected else 0,
        "selected_local_provider": selected.provider if selected else "",
        "selected_local_source_schema": selected.source_schema if selected else "",
        "selected_local_endpoint_scope": selected.endpoint_scope if selected else "",
        "selected_local_runtime_class": selected.runtime_class if selected else "",
        "selected_local_benchmark_state": selected_benchmark_state,
        "selected_local_benchmark_backed": selected_benchmark_state
        in {"production_backed", "staging_backed", "smoke_backed"},
        "spark_vllm_candidate_count": spark_vllm_candidate_count,
        "ollama_candidate_count": ollama_candidate_count,
        "offline_optimizer_state": offline_optimizer_state,
        "offline_first_candidate": bool(selected) or required_capacity <= 0,
        "lower_model_readiness": readiness,
        "validator_gate": readiness.get("validator_gate") or row.get("validator_gate"),
        "final_authority_required": final_authority_required,
        "targets": row.get("targets") if isinstance(row.get("targets"), dict) else {},
        "escalate_to_5_4_when": decision.get("escalate_to_5_4_when") or [],
        "escalate_to_5_5_when": decision.get("escalate_to_5_5_when") or [],
    }


def _slug(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "_", _norm(value))
    return clean.strip("_") or "unknown"


def _live_trial_profile(model: LocalModel) -> LowModelTrialProfile:
    max_autonomy = 2
    lane = "readonly_scout_worker"
    allowed = "read-only extraction and bounded draft work"
    blocked = "live mutation, external write, or final authority"
    gate = "5.4 verifier accepts sampled outputs and route receipts show no drift."
    if model.runtime_class == "spark_vllm":
        lane = "spark_vllm_scout"
        gate = "Spark vLLM receipts stay verifier-clean with no cloud fallback drift."
    if model.family == "coder":
        lane = (
            "spark_vllm_coder_scout"
            if model.runtime_class == "spark_vllm"
            else "coder_scout"
        )
        allowed = "known-file patch sketches and test-plan drafts"
        gate = "zero file-scope drift and verifier accepts the patch sketch."
    elif model.capacity_rank <= 1:
        max_autonomy = 1
        lane = "contract_only_worker"
        allowed = "strict JSON rewrites and checklist cleanup"
        gate = "strict JSON pass rate stays >=98% on contract-only cases."
    elif model.family == "frontier_local_shadow":
        lane = "frontier_shadow"
        allowed = "shadow review and disagreement analysis"
        gate = "shadow disagreements catch real defects without increasing noise."

    return LowModelTrialProfile(
        id=f"live_{_slug(model.endpoint)}_{_slug(model.model)}",
        label=f"Live local {model.model}",
        model=model.model,
        provider=model.endpoint,
        capacity_rank=model.capacity_rank,
        family=model.family,
        lane=lane,
        max_autonomy_level=max_autonomy,
        try_now=model.capacity_rank > 0,
        allowed_use=allowed,
        not_allowed_use=blocked,
        promotion_gate=gate,
        live_inventory_profile=True,
        runtime_provider=model.provider,
        runtime_class=model.runtime_class,
        endpoint=model.endpoint,
        source_schema=model.source_schema,
    )


def _profile_status_for_skill(
    profile: LowModelTrialProfile, row: dict[str, Any]
) -> tuple[str, list[str]]:
    decision = row.get("model_routing_decision")
    if not isinstance(decision, dict):
        decision = {}
    readiness = row.get("lower_model_readiness")
    if not isinstance(readiness, dict):
        readiness = {}
    minimum_tier = str(
        decision.get("minimum_model_tier")
        or row.get("minimum_matrix_tier")
        or "unknown"
    )
    required_capacity = TIER_REQUIRED_CAPACITY.get(minimum_tier, 3)
    final_authority_required = _requires_final_authority(row)
    requires_code = bool(row.get("requires_code"))
    requires_tools = bool(row.get("requires_tools"))
    reasons = [
        f"matrix_tier={minimum_tier}",
        f"required_capacity={required_capacity}",
        f"profile_capacity={profile.capacity_rank}",
    ]

    if required_capacity <= 0:
        return "deterministic_match", [*reasons, "no model required"]
    if final_authority_required:
        return (
            "draft_only_final_authority_hold",
            [*reasons, "final authority stays on 5.5/operator approval"],
        )
    if profile.capacity_rank < required_capacity:
        return "blocked_capacity", [*reasons, "profile below required capacity"]
    if profile.max_autonomy_level <= 0:
        return "blocked_autonomy", [*reasons, "profile is deterministic-only"]
    if profile.max_autonomy_level == 1:
        if requires_tools or requires_code:
            return (
                "contract_only_with_verifier",
                [*reasons, "tool/code work requires stronger verifier"],
            )
        return (
            "contract_only_candidate",
            [*reasons, "strict JSON/transform-only canary"],
        )

    if bool(readiness.get("can_shadow_roll_out_lower_final")) and bool(
        readiness.get("has_deterministic_validator")
    ):
        if profile.capacity_rank >= 3 and not requires_code:
            return (
                "validator_bounded_final_candidate",
                [*reasons, "deterministic validator available"],
            )
        return (
            "worker_with_5_4_verifier",
            [*reasons, "bounded worker with verifier acceptance"],
        )
    if bool(decision.get("requires_5_4_verifier")) or required_capacity >= 3:
        return (
            "worker_with_5_4_verifier",
            [*reasons, "5.4 verifier required by matrix"],
        )
    return "try_now_low_risk_candidate", [*reasons, "low-risk canary"]


def _float_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        targets = row.get("targets") if isinstance(row.get("targets"), dict) else {}
        try:
            value = float(targets.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            values.append(value)
    return values


def _accuracy_target_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    operational = _float_values(rows, "operational_accuracy")
    strict = _float_values(rows, "strict_accuracy")
    overreach = _float_values(rows, "max_overreach_risk")
    return {
        "evidence_type": "modeled_skill_matrix_targets",
        "live_observed_accuracy": None,
        "live_receipts_required": True,
        "target_operational_accuracy_min": round(min(operational), 4)
        if operational
        else 0.0,
        "target_operational_accuracy_median": round(median(operational), 4)
        if operational
        else 0.0,
        "target_strict_accuracy_min": round(min(strict), 4) if strict else 0.0,
        "target_strict_accuracy_median": round(median(strict), 4) if strict else 0.0,
        "max_overreach_risk_ceiling": round(max(overreach), 4) if overreach else 0.0,
    }


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _capability_phrases(status_counts: dict[str, int]) -> list[str]:
    phrases: list[str] = []
    if status_counts.get("deterministic_match", 0):
        phrases.append("deterministic status/count/diff work")
    if status_counts.get("contract_only_candidate", 0):
        phrases.append("strict JSON or checklist transforms")
    if status_counts.get("try_now_low_risk_candidate", 0):
        phrases.append("low-risk read-only extraction and summaries")
    if status_counts.get("worker_with_5_4_verifier", 0):
        phrases.append("bounded worker drafts with 5.4 verifier")
    if status_counts.get("validator_bounded_final_candidate", 0):
        phrases.append("validator-bounded shadow final candidates")
    return phrases


def _blocked_phrases(
    profile: LowModelTrialProfile, status_counts: dict[str, int]
) -> list[str]:
    blocked = [profile.not_allowed_use]
    if status_counts.get("draft_only_final_authority_hold", 0):
        blocked.append("final authority stays with Bedrock 5.5 or operator approval")
    if profile.max_autonomy_level <= 1:
        blocked.append("tool use, shell, code edits, and evidence adjudication")
    return [
        item
        for index, item in enumerate(blocked)
        if item and item not in blocked[:index]
    ]


def _profile_capability_summary(
    profile: LowModelTrialProfile,
    *,
    status_counts: dict[str, int],
    capability_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    verifier_required = status_counts.get(
        "worker_with_5_4_verifier", 0
    ) + status_counts.get("validator_bounded_final_candidate", 0)
    return {
        "schema": "norman.model-capability-row.v1",
        "profile_id": profile.id,
        "model": profile.model,
        "provider": profile.provider,
        "runtime_provider": profile.runtime_provider,
        "runtime_class": profile.runtime_class,
        "endpoint": profile.endpoint,
        "source_schema": profile.source_schema,
        "family": profile.family,
        "capacity_rank": profile.capacity_rank,
        "lane": profile.lane,
        "try_now": profile.try_now,
        "max_autonomy_level": profile.max_autonomy_level,
        "capability_skill_count": len(capability_rows),
        "can_do": _capability_phrases(status_counts),
        "cannot_do": _blocked_phrases(profile, status_counts),
        "domain_counts": _counts(capability_rows, "domain"),
        "family_counts": _counts(capability_rows, "family"),
        "status_counts": dict(sorted(status_counts.items())),
        "verifier_required_count": verifier_required,
        "final_authority_hold_count": status_counts.get(
            "draft_only_final_authority_hold", 0
        ),
        "accuracy_targets": _accuracy_target_summary(capability_rows),
        "promotion_gate": profile.promotion_gate,
    }


def build_low_model_trial_benchmark(
    rows: list[dict[str, Any]], inventory: list[LocalModel]
) -> dict[str, Any]:
    profiles = [
        *LOW_MODEL_TRIAL_PROFILES,
        *[_live_trial_profile(model) for model in inventory if model.capacity_rank > 0],
    ]
    seen: set[str] = set()
    unique_profiles: list[LowModelTrialProfile] = []
    for profile in profiles:
        if profile.id in seen:
            continue
        unique_profiles.append(profile)
        seen.add(profile.id)

    profile_rows: list[dict[str, Any]] = []
    for profile in unique_profiles:
        status_counts: dict[str, int] = {}
        recommended: list[dict[str, Any]] = []
        hold_examples: list[str] = []
        capability_rows: list[dict[str, Any]] = []
        for row in rows:
            status, reasons = _profile_status_for_skill(profile, row)
            status_counts[status] = status_counts.get(status, 0) + 1
            if status in CAPABILITY_STATUSES:
                capability_rows.append(row)
            if status in TRY_NOW_STATUSES and len(recommended) < 8:
                recommended.append(
                    {
                        "skill_id": row.get("skill_id"),
                        "domain": row.get("domain"),
                        "family": row.get("family"),
                        "status": status,
                        "reason": reasons[-1] if reasons else "",
                    }
                )
            elif status == "draft_only_final_authority_hold" and len(hold_examples) < 5:
                hold_examples.append(str(row.get("skill_id") or ""))

        try_now_candidate_count = sum(
            status_counts.get(status, 0) for status in TRY_NOW_STATUSES
        )
        verifier_required_count = status_counts.get(
            "worker_with_5_4_verifier", 0
        ) + status_counts.get("validator_bounded_final_candidate", 0)
        blocked_count = sum(
            count
            for status, count in status_counts.items()
            if status.startswith("blocked")
        )
        score = (
            try_now_candidate_count * 3
            + status_counts.get("validator_bounded_final_candidate", 0) * 2
            + status_counts.get("contract_only_candidate", 0)
            - status_counts.get("draft_only_final_authority_hold", 0)
            - blocked_count
        )
        profile_rows.append(
            {
                **profile.as_dict(),
                "skill_count": len(rows),
                "status_counts": dict(sorted(status_counts.items())),
                "capability_summary": _profile_capability_summary(
                    profile,
                    status_counts=status_counts,
                    capability_rows=capability_rows,
                ),
                "try_now_candidate_count": try_now_candidate_count,
                "verifier_required_count": verifier_required_count,
                "blocked_count": blocked_count,
                "final_authority_hold_count": status_counts.get(
                    "draft_only_final_authority_hold", 0
                ),
                "try_now_score": score,
                "recommended_first_skills": recommended,
                "final_authority_hold_examples": hold_examples,
                "promotion_blockers": [
                    profile.not_allowed_use,
                    profile.promotion_gate,
                ],
            }
        )

    def _profile_sort_family_rank(item: dict[str, Any]) -> int:
        family = str(item.get("family") or "")
        if family in {"bedrock_scout", "coder"}:
            return 0
        if family in {"cheap_cloud_worker", "small_local_worker"}:
            return 1
        if family in {"tiny_text_worker", "deterministic"}:
            return 2
        if family == "vision_local_worker":
            return 3
        return 4

    def _profile_sort_runtime_rank(item: dict[str, Any]) -> int:
        provider = str(item.get("provider") or "")
        runtime_provider = str(item.get("runtime_provider") or "")
        if item.get("runtime_class") == "spark_vllm" or runtime_provider == "vllm":
            return 0
        if item.get("live_inventory_profile") and runtime_provider == "ollama":
            return 1
        if provider in {"ollama", "ollama/vllm", "local/vllm"}:
            return 2
        if provider in {"openai", "aws-bedrock"}:
            return 3
        return 4

    profile_rows.sort(
        key=lambda item: (
            0 if item.get("try_now") else 1,
            -int(item.get("try_now_score") or 0),
            _profile_sort_runtime_rank(item),
            _profile_sort_family_rank(item),
            str(item.get("id") or ""),
        )
    )
    try_now_profiles = [
        row
        for row in profile_rows
        if row.get("try_now") and int(row.get("try_now_candidate_count") or 0) > 0
    ]
    live_try_now_profiles = [
        row for row in try_now_profiles if row.get("live_inventory_profile")
    ]
    live_spark_vllm_try_now_profiles = [
        row for row in live_try_now_profiles if row.get("runtime_class") == "spark_vllm"
    ]
    return {
        "schema": "norman.low-model-trial-benchmark.v1",
        "dry_run_only": True,
        "model_calls_executed": 0,
        "profile_count": len(profile_rows),
        "try_now_profile_count": len(try_now_profiles),
        "live_try_now_profile_count": len(live_try_now_profiles),
        "live_spark_vllm_try_now_profile_count": len(live_spark_vllm_try_now_profiles),
        "best_try_now_profile": try_now_profiles[0]["id"] if try_now_profiles else "",
        "best_live_try_now_profile": live_try_now_profiles[0]["id"]
        if live_try_now_profiles
        else "",
        "best_live_spark_vllm_try_now_profile": live_spark_vllm_try_now_profiles[0][
            "id"
        ]
        if live_spark_vllm_try_now_profiles
        else "",
        "hard_boundaries": [
            "No low-level profile gets live mutation or final authority.",
            "Verifier-required statuses must be accepted by 5.4/5.5 before operator-visible use.",
            "Contract-only profiles cannot use tools, shell, or working-tree writes.",
        ],
        "capability_matrix": [
            row["capability_summary"]
            for row in profile_rows
            if row.get("capability_summary")
        ],
        "profiles": profile_rows,
    }


def build_report(
    skill_matrix: dict[str, Any],
    ollama_report: dict[str, Any],
    *,
    extra_sense_reports: list[dict[str, Any]] | None = None,
    norllama_capabilities: dict[str, Any] | None = None,
    benchmark_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    norllama_sense = norllama_capabilities_as_sense_report(norllama_capabilities or {})
    sense_reports = [
        ollama_report,
        *(extra_sense_reports or []),
        *([norllama_sense] if norllama_sense else []),
    ]
    inventory = local_model_inventory(*sense_reports)
    benchmark_model_states = benchmark_packet_model_states(benchmark_packet or {})
    rows = [
        floor_for_skill(
            row,
            inventory,
            benchmark_model_states=benchmark_model_states,
        )
        for row in skill_matrix.get("rows") or []
        if isinstance(row, dict)
    ]
    status_counts: dict[str, int] = {}
    model_counts: dict[str, int] = {}
    provider_counts: dict[str, int] = {}
    runtime_counts: dict[str, int] = {}
    optimizer_state_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("local_floor_status") or "")
        status_counts[status] = status_counts.get(status, 0) + 1
        model = str(row.get("selected_local_model") or "")
        if model:
            model_counts[model] = model_counts.get(model, 0) + 1
        provider = str(row.get("selected_local_provider") or "")
        if provider:
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
        runtime = str(row.get("selected_local_runtime_class") or "")
        if runtime:
            runtime_counts[runtime] = runtime_counts.get(runtime, 0) + 1
        optimizer_state = str(row.get("offline_optimizer_state") or "unknown")
        optimizer_state_counts[optimizer_state] = (
            optimizer_state_counts.get(optimizer_state, 0) + 1
        )
    trial_benchmark = build_low_model_trial_benchmark(rows, inventory)
    spark_vllm_inventory_count = sum(
        1 for item in inventory if item.runtime_class == "spark_vllm"
    )
    ollama_inventory_count = sum(1 for item in inventory if item.provider == "ollama")
    return {
        "schema": SCHEMA,
        "generated_at": int(time.time()),
        "dry_run_only": True,
        "model_calls_executed": 0,
        "source_skill_matrix_schema": skill_matrix.get("schema"),
        "source_ollama_schema": ollama_report.get("schema"),
        "source_sense_schemas": [
            str(report.get("schema") or "")
            for report in sense_reports
            if isinstance(report, dict) and report.get("schema")
        ],
        "norllama_inventory": {
            "schema": "norman.local-model-skill-floor.norllama-inventory.v1",
            "source_schema": str((norllama_capabilities or {}).get("schema") or ""),
            "connected": bool(norllama_sense),
            "model_count": len(
                norllama_sense.get("endpoints", [{}])[0].get("models", [])
            )
            if norllama_sense
            else 0,
        },
        "benchmark_packet": {
            "schema": "norman.local-model-skill-floor.benchmark-packet.v1",
            "source_schema": str((benchmark_packet or {}).get("schema") or ""),
            "connected": bool(benchmark_model_states),
            "model_count": len(benchmark_model_states),
            "states": benchmark_model_states,
        },
        "summary": {
            "skill_count": len(rows),
            "online_local_model_count": len(inventory),
            "online_spark_vllm_model_count": spark_vllm_inventory_count,
            "online_ollama_model_count": ollama_inventory_count,
            "norllama_inventory_model_count": len(
                norllama_sense.get("endpoints", [{}])[0].get("models", [])
            )
            if norllama_sense
            else 0,
            "benchmark_packet_model_count": len(benchmark_model_states),
            "benchmark_backed_selected_skill_count": sum(
                1 for row in rows if row.get("selected_local_benchmark_backed")
            ),
            "local_candidate_skill_count": sum(
                1 for row in rows if row.get("selected_local_model")
            ),
            "offline_first_candidate_count": sum(
                1 for row in rows if row.get("offline_first_candidate")
            ),
            "spark_vllm_candidate_skill_count": sum(
                1 for row in rows if int(row.get("spark_vllm_candidate_count") or 0) > 0
            ),
            "spark_vllm_selected_skill_count": runtime_counts.get("spark_vllm", 0),
            "ollama_fallback_skill_count": optimizer_state_counts.get(
                "ollama_fallback_no_usable_spark_vllm", 0
            ),
            "validator_bounded_final_candidate_count": status_counts.get(
                "local_validator_bounded_final_candidate", 0
            ),
            "draft_only_final_authority_hold_count": status_counts.get(
                "local_draft_only_final_authority_hold", 0
            ),
            "no_local_candidate_count": status_counts.get("no_local_candidate", 0),
            "status_counts": status_counts,
            "selected_model_counts": dict(sorted(model_counts.items())),
            "selected_provider_counts": dict(sorted(provider_counts.items())),
            "selected_runtime_counts": dict(sorted(runtime_counts.items())),
            "offline_optimizer_state_counts": dict(
                sorted(optimizer_state_counts.items())
            ),
            "low_model_trial_profile_count": trial_benchmark["profile_count"],
            "low_model_try_now_profile_count": trial_benchmark["try_now_profile_count"],
            "live_low_model_try_now_profile_count": trial_benchmark[
                "live_try_now_profile_count"
            ],
            "live_spark_vllm_try_now_profile_count": trial_benchmark[
                "live_spark_vllm_try_now_profile_count"
            ],
            "best_low_model_try_now_profile": trial_benchmark["best_try_now_profile"],
            "best_live_low_model_try_now_profile": trial_benchmark[
                "best_live_try_now_profile"
            ],
            "best_live_spark_vllm_try_now_profile": trial_benchmark[
                "best_live_spark_vllm_try_now_profile"
            ],
        },
        "inventory": [item.as_dict() for item in inventory],
        "low_model_trial_benchmark": trial_benchmark,
        "rows": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Local Model Skill Floors",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Dry run only: {report['dry_run_only']}",
        f"- Skills: {summary['skill_count']}",
        f"- Online local models: {summary['online_local_model_count']}",
        f"- Online Spark/vLLM models: {summary['online_spark_vllm_model_count']}",
        f"- Online Ollama models: {summary['online_ollama_model_count']}",
        f"- Local candidate skills: {summary['local_candidate_skill_count']}",
        f"- Offline-first candidate skills: {summary['offline_first_candidate_count']}",
        f"- Spark/vLLM candidate skills: {summary['spark_vllm_candidate_skill_count']}",
        f"- Spark/vLLM selected skills: {summary['spark_vllm_selected_skill_count']}",
        f"- Ollama fallback skills: {summary['ollama_fallback_skill_count']}",
        f"- Validator-bounded final candidates: {summary['validator_bounded_final_candidate_count']}",
        f"- Draft-only final-authority holds: {summary['draft_only_final_authority_hold_count']}",
        f"- No local candidate: {summary['no_local_candidate_count']}",
        f"- Low-model trial profiles: {summary['low_model_trial_profile_count']}",
        f"- Try-now low-model profiles: {summary['low_model_try_now_profile_count']}",
        f"- Live try-now low-model profiles: {summary['live_low_model_try_now_profile_count']}",
        f"- Live Spark/vLLM try-now profiles: {summary['live_spark_vllm_try_now_profile_count']}",
        f"- Best try-now profile: `{summary['best_low_model_try_now_profile'] or 'none'}`",
        f"- Best live try-now profile: `{summary['best_live_low_model_try_now_profile'] or 'none'}`",
        f"- Best live Spark/vLLM try-now profile: `{summary['best_live_spark_vllm_try_now_profile'] or 'none'}`",
        "",
        "## Selected Model Counts",
        "",
    ]
    for model, count in summary["selected_model_counts"].items():
        lines.append(f"- `{model}`: {count}")
    lines.extend(["", "## Selected Runtime Counts", ""])
    for runtime, count in summary["selected_runtime_counts"].items():
        lines.append(f"- `{runtime}`: {count}")
    lines.extend(["", "## Offline Optimizer States", ""])
    for state, count in summary["offline_optimizer_state_counts"].items():
        lines.append(f"- `{state}`: {count}")
    trial = report.get("low_model_trial_benchmark", {})
    trial_profiles = trial.get("profiles") if isinstance(trial, dict) else []
    capability_matrix = (
        trial.get("capability_matrix") if isinstance(trial, dict) else []
    )
    if isinstance(capability_matrix, list) and capability_matrix:
        lines.extend(
            [
                "",
                "## Model Capability Matrix",
                "",
                "| Profile | Can Do | Modeled Op Target | Modeled Strict Target | Verifier | Final Holds | Cannot Do |",
                "|---|---|---:|---:|---:|---:|---|",
            ]
        )
        for item in capability_matrix[:16]:
            if not isinstance(item, dict):
                continue
            accuracy = (
                item.get("accuracy_targets")
                if isinstance(item.get("accuracy_targets"), dict)
                else {}
            )
            lines.append(
                "| `{profile}` | {can_do} | {op:.1%} | {strict:.1%} | {verifier} | {holds} | {cannot_do} |".format(
                    profile=item.get("profile_id") or "",
                    can_do=", ".join(item.get("can_do") or []) or "-",
                    op=float(accuracy.get("target_operational_accuracy_median") or 0.0),
                    strict=float(accuracy.get("target_strict_accuracy_median") or 0.0),
                    verifier=int(item.get("verifier_required_count") or 0),
                    holds=int(item.get("final_authority_hold_count") or 0),
                    cannot_do=", ".join(item.get("cannot_do") or []) or "-",
                )
            )
    if isinstance(trial_profiles, list) and trial_profiles:
        lines.extend(
            [
                "",
                "## Low-Level Trial Benchmark",
                "",
                "| Profile | ID | Try Now | Score | Candidates | Verifier Required | Final Holds | Blocked | Gate |",
                "|---|---|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for profile in trial_profiles[:16]:
            if not isinstance(profile, dict):
                continue
            lines.append(
                "| {label} | `{profile_id}` | {try_now} | {score} | {candidates} | {verifier} | {holds} | {blocked} | {gate} |".format(
                    label=profile.get("label") or profile.get("id") or "",
                    profile_id=profile.get("id") or "",
                    try_now="yes" if profile.get("try_now") else "no",
                    score=int(profile.get("try_now_score") or 0),
                    candidates=int(profile.get("try_now_candidate_count") or 0),
                    verifier=int(profile.get("verifier_required_count") or 0),
                    holds=int(profile.get("final_authority_hold_count") or 0),
                    blocked=int(profile.get("blocked_count") or 0),
                    gate=str(profile.get("promotion_gate") or "").replace("|", "/"),
                )
            )
        lines.extend(["", "### First Try-Now Skill Candidates", ""])
        for profile in trial_profiles[:6]:
            if not isinstance(profile, dict) or not profile.get("try_now"):
                continue
            skills = [
                str(item.get("skill_id") or "")
                for item in profile.get("recommended_first_skills") or []
                if isinstance(item, dict)
            ]
            if skills:
                lines.append(f"- `{profile.get('id')}`: {', '.join(skills[:8])}")
        lines.extend(["", "### Hard Boundaries", ""])
        for boundary in trial.get("hard_boundaries") or []:
            lines.append(f"- {boundary}")
    lines.extend(
        [
            "",
            "## Sample Floors",
            "",
            "| Skill | Domain | Matrix tier | Local model | Role | Status |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in report["rows"][:40]:
        lines.append(
            "| {skill} | {domain} | {tier} | {model} | {role} | {status} |".format(
                skill=row.get("skill_id") or "",
                domain=row.get("domain") or "",
                tier=row.get("minimum_matrix_tier") or "",
                model=row.get("selected_local_model") or "-",
                role=row.get("allowed_role") or "",
                status=row.get("local_floor_status") or "",
            )
        )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skill-matrix-json", type=Path, default=DEFAULT_SKILL_MATRIX_JSON
    )
    parser.add_argument(
        "--ollama-sense-json", type=Path, default=DEFAULT_OLLAMA_SENSE_JSON
    )
    parser.add_argument("--vllm-sense-json", type=Path, default=DEFAULT_VLLM_SENSE_JSON)
    parser.add_argument(
        "--norllama-capabilities-json",
        type=Path,
        default=DEFAULT_NORLLAMA_CAPABILITIES_JSON,
    )
    parser.add_argument(
        "--benchmark-packet-json",
        type=Path,
        default=DEFAULT_NORLLAMA_BENCHMARK_PACKET_JSON,
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(
        load_json(args.skill_matrix_json),
        load_optional_json(args.ollama_sense_json),
        extra_sense_reports=[load_optional_json(args.vllm_sense_json)],
        norllama_capabilities=load_optional_json(args.norllama_capabilities_json),
        benchmark_packet=load_optional_json(args.benchmark_packet_json),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": report["schema"],
                "output_json": str(args.output_json),
                "output_md": str(args.output_md),
                "summary": report["summary"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
