#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from runbook_hybrid_architecture_audit import DEFAULT_MIRROR_ROOT
from ticket_token_cost_ledger import append_record, estimate_usage_usd, pricing_for


DEFAULT_OUTPUT_JSON = Path("/tmp/norman_tui_benchmarks/gaphelp_ticket_loop_shadow.json")
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_benchmarks/gaphelp_ticket_loop_shadow.md")
DEFAULT_LEDGER_JSONL = Path("/tmp/norman_tui_benchmarks/ticket_token_cost_ledger.jsonl")
DEFAULT_HELPDESK_BENCHMARK_CASES = 36


@dataclass(frozen=True)
class TicketShape:
    ticket_id: str
    title: str
    category: str
    risk: str
    obviousness: float
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    blocked: bool = False
    approval_required: bool = False
    state_change_required: bool = False


@dataclass(frozen=True)
class CostLine:
    lane: str
    model: str
    price_basis: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    estimated_usd: float


@dataclass(frozen=True)
class HelpDeskCase:
    ticket_id: str
    title: str
    body: str
    expected_runbook: str
    expected_decision: str
    required_resolution_terms: tuple[str, ...]
    forbidden_resolution_terms: tuple[str, ...] = ()
    acceptable_runbooks: tuple[str, ...] = ()
    approval_required: bool = False
    blocked: bool = False
    input_tokens: int = 72_000
    cached_input_tokens: int = 16_000
    output_tokens: int = 3_600
    oracle_notes: str = ""


@dataclass(frozen=True)
class ModelCatalogEntry:
    route_id: str
    model: str
    label: str
    provider_surface: str
    provider: str
    service_tier: str
    region: str
    input_usd_per_1m: float
    cached_input_usd_per_1m: float | None
    output_usd_per_1m: float
    context_window_tokens: int | None
    max_output_tokens: int | None
    capability_tier: str
    recommended_roles: tuple[str, ...]
    supports_batch: bool
    supports_flex: bool
    supports_prompt_cache: bool
    supports_tools: bool
    price_source: str
    availability_notes: str
    latency_class: str = "standard"
    timing_target: str = "interactive"
    max_complexity: str = "unknown"
    subagent_role: str = "none"
    final_role: str = "none"
    eligible_runbook_scope: str = "unknown"
    eligible_runbooks: tuple[str, ...] = ()
    price_confidence: str = "public_rate_card"


@dataclass(frozen=True)
class ControlPlaneIssueClass:
    issue_id: str
    label: str
    examples: tuple[str, ...]
    authority_level: str
    required_quality: float
    target_operational_accuracy: float
    target_strict_accuracy: float
    max_overreach_risk: float
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    requires_tools: bool
    requires_final_close_authority: bool
    requires_frontier_verifier: bool
    local_only_allowed: bool = False
    notes: str = ""


@dataclass(frozen=True)
class FoundationalSkillCase:
    skill_id: str
    label: str
    family: str
    examples: tuple[str, ...]
    required_quality: float
    target_operational_accuracy: float
    target_strict_accuracy: float
    max_overreach_risk: float
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    local_only_allowed: bool = False
    requires_tools: bool = False
    requires_code: bool = False
    requires_state_change: bool = False
    requires_high_authority: bool = False
    requires_5_4_heavy_lift: bool = False
    requires_5_5_verifier: bool = False
    notes: str = ""


@dataclass(frozen=True)
class CandidateThresholdProfile:
    candidate_id: str
    label: str
    catalog_route_id: str
    reasoning_effort: str
    base_quality: float
    output_multiplier: float
    can_final_close: bool
    can_high_authority: bool
    status: str
    notes: str = ""


@dataclass(frozen=True)
class PolicyResult:
    policy_id: str
    label: str
    description: str
    backlog_seen: int
    triaged: int
    attempted: int
    completed_shadow: int
    approval_stops: int
    blocked_stops: int
    skipped_budget: int
    total_input_tokens: int
    total_cached_input_tokens: int
    total_output_tokens: int
    estimated_usd: float
    estimated_usd_if_hourly: float
    estimated_usd_if_daily_once: float
    steady_state_unchanged_usd: float
    within_budget: bool
    notes: tuple[str, ...]


@dataclass(frozen=True)
class GapHelpDeploymentScenario:
    scenario_id: str
    label: str
    family: str
    owner_tui: str
    tenant_scope: str
    issue_class_id: str
    skill_ids: tuple[str, ...]
    ticket_ids: tuple[str, ...]
    runbooks: tuple[str, ...]
    rollout_phase: str
    deploy_candidate: bool
    recommended_first_tui: bool
    blocked_actions: tuple[str, ...]
    evidence_required: tuple[str, ...]
    candidate_hint_id: str = ""
    notes: str = ""


RUNBOOK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "MP": (
        "missing price",
        "wrong price",
        "price missing",
        "pricing",
        "offer mode",
        "carrier offer",
    ),
    "MPR": (
        "missing product",
        "product absent",
        "not showing product",
        "new product creation",
    ),
    "IS": (
        "wrong spec",
        "incorrect spec",
        "wrong merchant sku",
        "bad attribute",
        "spec correction",
    ),
    "PDR": (
        "delete product",
        "suppress",
        "retire product",
        "merge product",
        "rehome product",
        "discontinued product",
    ),
    "DU": ("dead url", "broken link", "obsolete pdp", "404 pdp"),
    "PH": (
        "parser",
        "rendered fields",
        "dar",
        "page artifact",
        "thin payload",
    ),
    "WPL": (
        "watchlist",
        "placement",
        "normal tracking",
        "lifecycle alignment",
        "gapi placement",
    ),
    "HCL": ("historical correction", "late reporting", "bounded historical"),
    "BR": ("wayback", "external anchor", "continuity bridge", "missing window"),
    "MID": ("wrong country", "country attribution", "internationalized"),
    "CEI": (
        "coverage expansion",
        "controlled intake",
        "approved scope",
        "staged rollout",
    ),
    "LOBM": ("bulk replay", "large one-off", "migration", "years of replay"),
    "SH": ("schema", "header", "field exposed", "export column", "spec header"),
    "EPF": ("etl", "processing job", "processor failing", "structurally bad"),
    "SI": ("source incident", "ingestion degraded", "landing empty", "delayed feed"),
    "SDC": ("source export", "data contract", "feed shape", "provider column"),
    "RDF": (
        "report download",
        "download fails",
        "export generation",
        "product info fields report",
    ),
    "MRI": ("media", "roi rendering", "ad image", "creative image"),
    "TRC": ("taxonomy", "reclassification", "category intent", "product type"),
    "SDI": ("definition integrity", "required fields", "spec completeness"),
    "TMD": (
        "tmi numbers",
        "marketshare",
        "mindshare",
        "duplicate brand",
        "unexpected category",
        "numbers disagree",
    ),
    "DMR": (
        "dashboard",
        "metric surface",
        "stale dashboard",
        "quicksight refresh",
        "refresh visibility",
    ),
    "HRB": (
        "historical restatement",
        "visible historical change",
        "backfill explanation",
    ),
    "AAE": ("access tier", "approval path", "mcp access", "quicksuite"),
    "CDH": (
        "deliverable",
        "stale file",
        "manual delivery",
        "match-rate",
        "customer delivery",
    ),
    "PFG": ("feature guardrail", "admin workflow", "post-merge", "linked pr"),
    "PSM": ("surface migration", "sunset", "replacement readiness", "old surface"),
    "SQC": ("survey question", "variable", "response option", "programming logic"),
    "S2B": ("feasibility", "new scope", "trial", "poc", "upsell"),
    "S7": ("sold implementation", "customer launch", "stage 7", "onboarding"),
    "S8": (
        "offboarding",
        "entitlement drift",
        "access removal",
        "contract sunset",
        "vanta",
    ),
}


RUNBOOK_RESOLUTION_TERMS: dict[str, tuple[str, ...]] = {
    "MP": ("price", "source evidence", "before/after proof"),
    "MPR": ("product identity", "discovery evidence", "intake path"),
    "IS": ("spec", "record path", "validation evidence"),
    "PDR": ("visibility", "approval", "reversible"),
    "DU": ("replacement url", "pdp status", "public surface check"),
    "PH": ("parser", "rendered field evidence", "source artifact"),
    "WPL": ("watchlist", "placement", "scheduled flow"),
    "HCL": ("historical window", "bounded correction", "visible history proof"),
    "BR": ("external anchor", "missing window", "continuity evidence"),
    "MID": ("country attribution", "affected rows", "surface parity"),
    "CEI": ("approved scope", "staged rollout", "intake evidence"),
    "LOBM": ("replay scope", "migration plan", "rollback"),
    "SH": ("schema", "downstream exposure", "public surface check"),
    "EPF": ("job failure", "processor evidence", "rerun proof"),
    "SI": ("source flow", "landing evidence", "freshness proof"),
    "SDC": ("source contract", "export sample", "vendor/source owner"),
    "RDF": ("report", "download proof", "customer-facing check"),
    "MRI": ("media", "render proof", "customer-facing check"),
    "TRC": ("taxonomy intent", "product decision", "affected outputs"),
    "SDI": ("definition integrity", "required fields", "approved definition"),
    "TMD": ("numbers", "source rows", "explanation"),
    "DMR": ("dashboard", "refresh proof", "visible metric check"),
    "HRB": ("restatement", "backfill explanation", "visible history proof"),
    "AAE": ("access policy", "approval tier", "customer-safe messaging"),
    "CDH": ("deliverable", "sla", "customer-safe response"),
    "PFG": ("guardrail", "release validation", "linked pr"),
    "PSM": ("surface parity", "migration", "customer communication"),
    "SQC": ("survey contract", "approval", "output validation"),
    "S2B": ("feasibility", "scope evidence", "approval source"),
    "S7": ("launch acceptance", "surface checklist", "customer proof"),
    "S8": ("entitlement", "access proof", "reversible deactivation"),
}


APPROVAL_ONLY_RUNBOOKS = (
    "PDR",
    "CEI",
    "LOBM",
    "HRB",
    "AAE",
    "SQC",
    "S7",
    "S8",
)
CLARIFY_ONLY_RUNBOOKS = ("ABSTAIN",)
SAFE_CLOSE_RUNBOOKS = tuple(
    code for code in RUNBOOK_RESOLUTION_TERMS if code not in set(APPROVAL_ONLY_RUNBOOKS)
)
ROUTE_ALL_RUNBOOKS = tuple(
    sorted(set(RUNBOOK_RESOLUTION_TERMS) | set(CLARIFY_ONLY_RUNBOOKS))
)


def _latency_metadata(service_tier: str) -> tuple[str, str]:
    clean = service_tier.strip().lower()
    if clean == "priority":
        return "fast", "<5m urgent/operator-facing"
    if clean == "batch":
        return "offline", "overnight/bulk replay"
    if clean == "flex":
        return "flex", "interactive when variable latency is acceptable"
    return "standard", "interactive/steady loop"


def _route_role_metadata(
    *,
    route_id: str,
    capability_tier: str,
    service_tier: str,
    roles: tuple[str, ...],
    supports_tools: bool,
) -> dict[str, Any]:
    latency_class, timing_target = _latency_metadata(service_tier)
    capability = capability_tier.strip().lower()
    role_text = " ".join(roles).lower()

    max_complexity = "unknown"
    subagent_role = "none"
    final_role = "none"
    eligible_runbook_scope = "unknown"
    eligible_runbooks: tuple[str, ...] = ()

    if capability in {"classifier", "cheap-classifier"} or "classifier" in role_text:
        max_complexity = "watch/classify/dedupe"
        subagent_role = "route-only classifier"
        final_role = "none"
        eligible_runbook_scope = "route all; no close"
        eligible_runbooks = ROUTE_ALL_RUNBOOKS
    elif capability.startswith(
        (
            "cheap-coder",
            "coder-scout",
            "cheap-general",
            "reasoning-scout",
            "synthesis-scout",
            "general-scout",
        )
    ):
        max_complexity = "runbook route + evidence draft"
        subagent_role = "cheap draft worker"
        final_role = "none"
        eligible_runbook_scope = "safe draft; approval stops only"
        eligible_runbooks = tuple(
            sorted(set(SAFE_CLOSE_RUNBOOKS) | set(APPROVAL_ONLY_RUNBOOKS))
        )
    elif capability.startswith("worker"):
        max_complexity = "safe low-risk draft"
        subagent_role = "draft worker"
        final_role = "sample verifier only"
        eligible_runbook_scope = "safe draft; no high-authority close"
        eligible_runbooks = SAFE_CLOSE_RUNBOOKS
    elif capability.startswith(("strong",)):
        max_complexity = "safe close + sampled high-authority plan"
        subagent_role = "resolver/verifier"
        final_role = "safe close; high authority requires verifier"
        eligible_runbook_scope = "safe close; approval runbooks plan only"
        eligible_runbooks = tuple(
            sorted(set(SAFE_CLOSE_RUNBOOKS) | set(APPROVAL_ONLY_RUNBOOKS))
        )
    elif capability.startswith(("frontier",)):
        max_complexity = "high-authority plan/verifier"
        subagent_role = "expensive resolver"
        final_role = "final verifier/high-authority plan"
        eligible_runbook_scope = "all runbooks with approval gates"
        eligible_runbooks = ROUTE_ALL_RUNBOOKS

    if route_id == "bedrock_moonshot_kimi_k2_5_standard_us":
        max_complexity = "long-context route + draft compare"
        subagent_role = "benchmark scout/draft worker"
        final_role = "none until tools wired"
        eligible_runbook_scope = "route all; safe draft only"
        eligible_runbooks = ROUTE_ALL_RUNBOOKS

    if not supports_tools and "close" in final_role:
        final_role = "draft/verifier text only; tool execution unavailable"

    return {
        "latency_class": latency_class,
        "timing_target": timing_target,
        "max_complexity": max_complexity,
        "subagent_role": subagent_role,
        "final_role": final_role,
        "eligible_runbook_scope": eligible_runbook_scope,
        "eligible_runbooks": eligible_runbooks,
    }


OPENAI_PRICING_SOURCE = "https://developers.openai.com/api/docs/pricing"
BEDROCK_PRICING_SOURCE = "https://aws.amazon.com/bedrock/pricing/"
BEDROCK_GPT_OSS_20B_SOURCE = (
    "https://docs.aws.amazon.com/bedrock/latest/userguide/"
    "model-card-openai-gpt-oss-20b.html"
)
BEDROCK_GPT_OSS_120B_SOURCE = (
    "https://docs.aws.amazon.com/bedrock/latest/userguide/"
    "model-card-openai-gpt-oss-120b.html"
)
BEDROCK_KIMI_K2_5_SOURCE = (
    "https://docs.aws.amazon.com/bedrock/latest/userguide/"
    "model-card-moonshot-ai-kimi-k2-5.html"
)
LOCAL_DGX_SPARK_SOURCE = "local operator DGX Spark / Spark 2x capacity model"
ANTHROPIC_MODELS_SOURCE = (
    "https://platform.claude.com/docs/en/about-claude/models/overview"
)
ANTHROPIC_PRICING_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"


def _direct_entry(
    *,
    route_id: str,
    model: str,
    label: str,
    service_tier: str,
    capability_tier: str,
    roles: tuple[str, ...],
) -> ModelCatalogEntry:
    price_basis = (
        "openai-direct-flex" if service_tier == "flex" else "openai-direct-standard"
    )
    rates = pricing_for(model, price_basis)
    if rates is None:
        raise ValueError(f"missing OpenAI direct price for {model}/{service_tier}")
    if service_tier == "batch":
        flex_rates = pricing_for(model, "openai-direct-flex")
        if flex_rates is None:
            raise ValueError(f"missing OpenAI batch-equivalent price for {model}")
        rates = flex_rates
    if service_tier == "priority":
        rates = {
            "input": rates["input"] * 2.5,
            "cached_input": rates["cached_input"] * 2.5,
            "output": rates["output"] * 2.5,
        }
    metadata = _route_role_metadata(
        route_id=route_id,
        capability_tier=capability_tier,
        service_tier=service_tier,
        roles=roles,
        supports_tools=True,
    )
    return ModelCatalogEntry(
        route_id=route_id,
        model=model,
        label=label,
        provider_surface="openai-direct",
        provider="OpenAI",
        service_tier=service_tier,
        region="global/direct",
        input_usd_per_1m=float(rates["input"]),
        cached_input_usd_per_1m=float(rates["cached_input"]),
        output_usd_per_1m=float(rates["output"]),
        context_window_tokens=1_050_000 if model in {"gpt-5.5", "gpt-5.4"} else None,
        max_output_tokens=128_000 if model in {"gpt-5.5", "gpt-5.4"} else None,
        capability_tier=capability_tier,
        recommended_roles=roles,
        supports_batch=service_tier == "batch",
        supports_flex=service_tier == "flex",
        supports_prompt_cache=True,
        supports_tools=True,
        price_source=OPENAI_PRICING_SOURCE,
        availability_notes=(
            "Priority/Fast is modeled with the repo UI's 2.5x standard "
            "multiplier. Batch/Flex are discounted direct OpenAI processing "
            "modes; batch is offline and flex is variable-latency."
        ),
        price_confidence="public_rate_card_with_local_priority_multiplier"
        if service_tier == "priority"
        else "public_rate_card",
        **metadata,
    )


def _catalog_entry(
    *,
    route_id: str,
    model: str,
    label: str,
    provider_surface: str,
    provider: str,
    service_tier: str,
    region: str,
    input_price: float,
    output_price: float,
    cached_input_price: float | None = None,
    context_window_tokens: int | None = None,
    max_output_tokens: int | None = None,
    capability_tier: str,
    roles: tuple[str, ...],
    supports_batch: bool = False,
    supports_flex: bool = False,
    supports_prompt_cache: bool = False,
    supports_tools: bool = False,
    price_source: str = BEDROCK_PRICING_SOURCE,
    availability_notes: str = "",
    latency_class: str = "",
    timing_target: str = "",
    max_complexity: str = "",
    subagent_role: str = "",
    final_role: str = "",
    eligible_runbook_scope: str = "",
    eligible_runbooks: tuple[str, ...] = (),
    price_confidence: str = "public_rate_card",
) -> ModelCatalogEntry:
    metadata = _route_role_metadata(
        route_id=route_id,
        capability_tier=capability_tier,
        service_tier=service_tier,
        roles=roles,
        supports_tools=supports_tools,
    )
    return ModelCatalogEntry(
        route_id=route_id,
        model=model,
        label=label,
        provider_surface=provider_surface,
        provider=provider,
        service_tier=service_tier,
        region=region,
        input_usd_per_1m=input_price,
        cached_input_usd_per_1m=cached_input_price,
        output_usd_per_1m=output_price,
        context_window_tokens=context_window_tokens,
        max_output_tokens=max_output_tokens,
        capability_tier=capability_tier,
        recommended_roles=roles,
        supports_batch=supports_batch,
        supports_flex=supports_flex,
        supports_prompt_cache=supports_prompt_cache,
        supports_tools=supports_tools,
        price_source=price_source,
        availability_notes=availability_notes,
        latency_class=latency_class or str(metadata["latency_class"]),
        timing_target=timing_target or str(metadata["timing_target"]),
        max_complexity=max_complexity or str(metadata["max_complexity"]),
        subagent_role=subagent_role or str(metadata["subagent_role"]),
        final_role=final_role or str(metadata["final_role"]),
        eligible_runbook_scope=eligible_runbook_scope
        or str(metadata["eligible_runbook_scope"]),
        eligible_runbooks=eligible_runbooks or tuple(metadata["eligible_runbooks"]),
        price_confidence=price_confidence,
    )


def model_catalog_entries() -> tuple[ModelCatalogEntry, ...]:
    return (
        _direct_entry(
            route_id="openai_direct_gpt_5_5_standard",
            model="gpt-5.5",
            label="OpenAI GPT-5.5 standard",
            service_tier="standard",
            capability_tier="frontier",
            roles=("hard-ticket resolver", "final verifier", "long-context coding"),
        ),
        _direct_entry(
            route_id="openai_direct_gpt_5_5_priority",
            model="gpt-5.5",
            label="OpenAI GPT-5.5 priority fast",
            service_tier="priority",
            capability_tier="frontier-fast",
            roles=(
                "urgent hard-ticket resolver",
                "urgent final verifier",
                "operator-facing fast lane",
            ),
        ),
        _direct_entry(
            route_id="openai_direct_gpt_5_5_flex",
            model="gpt-5.5",
            label="OpenAI GPT-5.5 flex",
            service_tier="flex",
            capability_tier="frontier-discount",
            roles=(
                "cheap interactive hard-ticket resolver",
                "final verifier when latency can flex",
            ),
        ),
        _direct_entry(
            route_id="openai_direct_gpt_5_5_batch",
            model="gpt-5.5",
            label="OpenAI GPT-5.5 batch",
            service_tier="batch",
            capability_tier="frontier-offline",
            roles=("nightly replay", "offline benchmark", "bulk verifier"),
        ),
        _direct_entry(
            route_id="openai_direct_gpt_5_4_standard",
            model="gpt-5.4",
            label="OpenAI GPT-5.4 standard",
            service_tier="standard",
            capability_tier="strong",
            roles=("price-performance resolver", "fallback verifier"),
        ),
        _direct_entry(
            route_id="openai_direct_gpt_5_4_priority",
            model="gpt-5.4",
            label="OpenAI GPT-5.4 priority fast",
            service_tier="priority",
            capability_tier="strong-fast",
            roles=(
                "urgent price-performance resolver",
                "urgent fallback verifier",
                "operator-facing fast lane",
            ),
        ),
        _direct_entry(
            route_id="openai_direct_gpt_5_4_flex",
            model="gpt-5.4",
            label="OpenAI GPT-5.4 flex",
            service_tier="flex",
            capability_tier="strong-discount",
            roles=("cheap resolver", "interactive worker", "sample verifier"),
        ),
        _direct_entry(
            route_id="openai_direct_gpt_5_4_batch",
            model="gpt-5.4",
            label="OpenAI GPT-5.4 batch",
            service_tier="batch",
            capability_tier="strong-offline",
            roles=("nightly replay", "bulk draft resolver"),
        ),
        _direct_entry(
            route_id="openai_direct_gpt_5_4_mini_flex",
            model="gpt-5.4-mini",
            label="OpenAI GPT-5.4 mini flex",
            service_tier="flex",
            capability_tier="worker",
            roles=("triage", "runbook selector", "low-risk draft worker"),
        ),
        _direct_entry(
            route_id="openai_direct_gpt_5_4_nano_flex",
            model="gpt-5.4-nano",
            label="OpenAI GPT-5.4 nano flex",
            service_tier="flex",
            capability_tier="classifier",
            roles=("cheap classifier", "ticket bucketing", "watch-loop scorer"),
        ),
        _catalog_entry(
            route_id="anthropic_direct_claude_opus_4_7_standard",
            model="claude-opus-4-7",
            label="Claude Opus 4.7 API",
            provider_surface="anthropic-direct",
            provider="Anthropic",
            service_tier="standard",
            region="global/direct",
            input_price=5.00,
            cached_input_price=0.50,
            output_price=25.00,
            context_window_tokens=1_000_000,
            max_output_tokens=128_000,
            capability_tier="frontier-opus",
            roles=(
                "long-horizon agentic work",
                "complex coding verifier",
                "benchmark frontier baseline",
            ),
            supports_batch=True,
            supports_prompt_cache=True,
            supports_tools=True,
            price_source=ANTHROPIC_PRICING_SOURCE,
            availability_notes=(
                "Anthropic public docs list Claude Opus 4.7 at $5 input/"
                "$25 output per MTok, with batch and prompt-cache pricing. "
                "Modeled here as a shadow/live-probe baseline until TUI live "
                "runner receipts are captured."
            ),
            price_confidence=("public_anthropic_rate_card; shadow_until_live_receipts"),
        ),
        _catalog_entry(
            route_id="anthropic_direct_claude_opus_4_8_standard",
            model="claude-opus-4-8",
            label="Claude Opus 4.8 API",
            provider_surface="anthropic-direct",
            provider="Anthropic",
            service_tier="standard",
            region="global/direct",
            input_price=5.00,
            cached_input_price=0.50,
            output_price=25.00,
            context_window_tokens=1_000_000,
            max_output_tokens=128_000,
            capability_tier="frontier-opus-latest",
            roles=(
                "complex reasoning",
                "long-horizon agentic coding",
                "high-autonomy benchmark baseline",
            ),
            supports_batch=True,
            supports_prompt_cache=True,
            supports_tools=True,
            price_source=ANTHROPIC_MODELS_SOURCE,
            availability_notes=(
                "Anthropic docs describe Claude Opus 4.8 as the current "
                "Opus-tier model for complex reasoning and agentic coding, "
                "with high effort as the documented default. Modeled here as "
                "a shadow/live-probe baseline until TUI live runner receipts "
                "are captured."
            ),
            price_confidence=("public_anthropic_rate_card; shadow_until_live_receipts"),
        ),
        _catalog_entry(
            route_id="bedrock_openai_gpt_5_5_ondemand_us_east_2",
            model="openai.gpt-5.5",
            label="Bedrock OpenAI GPT-5.5 on-demand",
            provider_surface="aws-bedrock",
            provider="OpenAI on Amazon Bedrock",
            service_tier="on-demand",
            region="us-east-2",
            input_price=5.50,
            cached_input_price=0.55,
            output_price=33.00,
            context_window_tokens=272_000,
            max_output_tokens=None,
            capability_tier="frontier-governed",
            roles=("AWS-governed hard-ticket resolver", "final verifier"),
            supports_prompt_cache=True,
            supports_tools=True,
            availability_notes=(
                "AWS public price row is Geo/In-region on-demand inference; "
                "no public Bedrock frontier Flex/Batch row is modeled here."
            ),
        ),
        _catalog_entry(
            route_id="bedrock_openai_gpt_5_4_ondemand_us_east_2",
            model="openai.gpt-5.4",
            label="Bedrock OpenAI GPT-5.4 on-demand",
            provider_surface="aws-bedrock",
            provider="OpenAI on Amazon Bedrock",
            service_tier="on-demand",
            region="us-east-1/us-east-2/us-west-2",
            input_price=2.75,
            cached_input_price=0.275,
            output_price=16.50,
            context_window_tokens=272_000,
            max_output_tokens=None,
            capability_tier="strong-governed",
            roles=("AWS-governed price-performance resolver", "fallback verifier"),
            supports_prompt_cache=True,
            supports_tools=True,
            availability_notes=(
                "AWS lists GPT-5.4 at half the GPT-5.5 on-demand token price."
            ),
        ),
        _catalog_entry(
            route_id="bedrock_gpt_oss_20b_flex_ap_southeast_2",
            model="openai.gpt-oss-20b-1:0",
            label="Bedrock GPT OSS 20B flex",
            provider_surface="aws-bedrock",
            provider="OpenAI OSS on Amazon Bedrock",
            service_tier="flex",
            region="ap-southeast-2 public price row",
            input_price=0.0361,
            output_price=0.1545,
            context_window_tokens=128_000,
            max_output_tokens=16_000,
            capability_tier="cheap-coder",
            roles=("triage", "runbook selector", "cheap coding scout"),
            supports_flex=True,
            supports_tools=True,
            price_source=BEDROCK_GPT_OSS_20B_SOURCE,
            availability_notes=(
                "AWS model card shows broad regional availability, but the "
                "pricing HTML currently exposes this Flex row for Sydney."
            ),
        ),
        _catalog_entry(
            route_id="bedrock_gpt_oss_20b_batch_ap_southeast_2",
            model="openai.gpt-oss-20b-1:0",
            label="Bedrock GPT OSS 20B batch",
            provider_surface="aws-bedrock",
            provider="OpenAI OSS on Amazon Bedrock",
            service_tier="batch",
            region="ap-southeast-2 public price row",
            input_price=0.0361,
            output_price=0.1545,
            context_window_tokens=128_000,
            max_output_tokens=16_000,
            capability_tier="cheap-coder-offline",
            roles=("nightly triage", "bulk runbook selection", "offline draft scout"),
            supports_batch=True,
            supports_tools=True,
            price_source=BEDROCK_GPT_OSS_20B_SOURCE,
            availability_notes="Batch price row is published for Sydney in AWS HTML.",
        ),
        _catalog_entry(
            route_id="bedrock_gpt_oss_120b_flex_ap_southeast_2",
            model="openai.gpt-oss-120b-1:0",
            label="Bedrock GPT OSS 120B flex",
            provider_surface="aws-bedrock",
            provider="OpenAI OSS on Amazon Bedrock",
            service_tier="flex",
            region="ap-southeast-2 public price row",
            input_price=0.0773,
            output_price=0.3090,
            context_window_tokens=128_000,
            max_output_tokens=16_000,
            capability_tier="reasoning-scout",
            roles=("cheap reasoning scout", "draft resolver", "coder worker"),
            supports_flex=True,
            supports_tools=True,
            price_source=BEDROCK_GPT_OSS_120B_SOURCE,
            availability_notes=(
                "Good candidate for shadow worker lanes; not equivalent to "
                "frontier GPT-5.5 verification."
            ),
        ),
        _catalog_entry(
            route_id="bedrock_gpt_oss_120b_batch_ap_southeast_2",
            model="openai.gpt-oss-120b-1:0",
            label="Bedrock GPT OSS 120B batch",
            provider_surface="aws-bedrock",
            provider="OpenAI OSS on Amazon Bedrock",
            service_tier="batch",
            region="ap-southeast-2 public price row",
            input_price=0.0773,
            output_price=0.3090,
            context_window_tokens=128_000,
            max_output_tokens=16_000,
            capability_tier="reasoning-scout-offline",
            roles=("offline draft resolver", "bulk code/reasoning scout"),
            supports_batch=True,
            supports_tools=True,
            price_source=BEDROCK_GPT_OSS_120B_SOURCE,
            availability_notes="Batch price row is published for Sydney in AWS HTML.",
        ),
        _catalog_entry(
            route_id="bedrock_qwen3_coder_30b_flex_ap_southeast_2",
            model="qwen.qwen3-coder-30b-a3b",
            label="Bedrock Qwen3 Coder 30B flex",
            provider_surface="aws-bedrock",
            provider="Qwen on Amazon Bedrock",
            service_tier="flex",
            region="ap-southeast-2 public price row",
            input_price=0.0773,
            output_price=0.3090,
            capability_tier="coder-scout",
            roles=("cheap code worker", "runbook edit draft", "benchmark scout"),
            supports_flex=True,
            supports_batch=True,
            price_source=BEDROCK_PRICING_SOURCE,
            availability_notes="Published Flex/Batch pricing row is Sydney.",
        ),
        _catalog_entry(
            route_id="local_dgx_spark_qwen3_coder_30b",
            model="qwen3-coder-30b-a3b",
            label="DGX Spark Qwen3 Coder 30B local",
            provider_surface="local-dgx-spark",
            provider="Local DGX Spark",
            service_tier="local",
            region="operator LAN",
            input_price=0.0,
            cached_input_price=0.0,
            output_price=0.0,
            context_window_tokens=128_000,
            max_output_tokens=16_000,
            capability_tier="local-coder-scout",
            roles=(
                "local code draft",
                "fixture generation",
                "runbook edit scout",
                "validated extraction",
            ),
            supports_batch=True,
            supports_prompt_cache=True,
            supports_tools=True,
            price_source=LOCAL_DGX_SPARK_SOURCE,
            availability_notes=(
                "Modeled as zero marginal token cost on already-owned local DGX "
                "Spark capacity. Excludes hardware, power, queueing, warmup, and "
                "operator maintenance. Must be paired with validators or a frontier "
                "verifier before live authority."
            ),
            latency_class="interactive-local-after-warmup",
            timing_target="interactive after model is warm; batch when cold",
            max_complexity="bounded code/data draft with deterministic checks",
            subagent_role="local Spark draft worker",
            final_role="no external final authority",
            eligible_runbook_scope="validated local/offline work only",
            eligible_runbooks=(
                "fixture generation",
                "file comprehension",
                "source extraction",
                "bounded coding draft",
            ),
            price_confidence="local_marginal_cost_estimate_excludes_capex_power",
        ),
        _catalog_entry(
            route_id="local_dgx_spark2_gpt_oss_120b",
            model="gpt-oss-120b",
            label="DGX Spark 2x GPT OSS 120B local",
            provider_surface="local-dgx-spark",
            provider="Local DGX Spark 2x",
            service_tier="local",
            region="operator LAN",
            input_price=0.0,
            cached_input_price=0.0,
            output_price=0.0,
            context_window_tokens=128_000,
            max_output_tokens=16_000,
            capability_tier="local-reasoning-scout",
            roles=(
                "local reasoning scout",
                "batch replay draft resolver",
                "offline anomaly analysis",
                "tool-plan draft",
            ),
            supports_batch=True,
            supports_prompt_cache=True,
            supports_tools=True,
            price_source=LOCAL_DGX_SPARK_SOURCE,
            availability_notes=(
                "Modeled as zero marginal token cost on paired local DGX Spark "
                "capacity. Prior canary evidence showed GPT OSS 120B can pass "
                "trivial sentinel checks but may cold-start slowly, so the matrix "
                "treats it as a high-value batch/offload worker rather than an "
                "interactive final authority."
            ),
            latency_class="batch-local-or-warm-interactive",
            timing_target="batch/offline by default; interactive only if warm",
            max_complexity="reasoning scout with verifier gate",
            subagent_role="local Spark reasoning worker",
            final_role="no external final authority",
            eligible_runbook_scope="offline replay and validated scout work",
            eligible_runbooks=(
                "anomaly triage",
                "checkpoint continuation draft",
                "runbook comparison",
                "shadow benchmark replay",
            ),
            price_confidence="local_marginal_cost_estimate_excludes_capex_power",
        ),
        _catalog_entry(
            route_id="bedrock_deepseek_v3_2_standard_us",
            model="deepseek.v3-2",
            label="Bedrock DeepSeek v3.2 standard",
            provider_surface="aws-bedrock",
            provider="DeepSeek on Amazon Bedrock",
            service_tier="standard",
            region="us-east-1/us-east-2/us-west-2",
            input_price=0.62,
            output_price=1.85,
            capability_tier="reasoning-scout",
            roles=("analysis scout", "draft resolver", "compare lane"),
            supports_flex=False,
            price_source=BEDROCK_PRICING_SOURCE,
            availability_notes="US standard row; Flex row is not modeled for v3.2.",
        ),
        _catalog_entry(
            route_id="bedrock_moonshot_kimi_k2_5_standard_us",
            model="moonshotai.kimi-k2.5",
            label="Bedrock Moonshot Kimi K2.5 standard",
            provider_surface="aws-bedrock",
            provider="Moonshot AI on Amazon Bedrock",
            service_tier="standard",
            region="us-east-1/us-east-2/us-west-2",
            input_price=0.60,
            output_price=3.00,
            context_window_tokens=256_000,
            max_output_tokens=16_000,
            capability_tier="reasoning-scout",
            roles=(
                "long-context scout",
                "draft resolver",
                "benchmark compare lane",
            ),
            supports_flex=False,
            supports_tools=False,
            price_source=BEDROCK_PRICING_SOURCE,
            availability_notes=(
                "AWS Bedrock Kimi K2.5 is modeled from the public Bedrock row. "
                "This TUI currently marks Kimi as benchmark/planned and not "
                "wired for live tool execution."
            ),
            price_confidence="public_rate_card; tui_execution_planned_offline",
        ),
        _catalog_entry(
            route_id="bedrock_gemma_3_27b_standard_us",
            model="google.gemma-3-27b",
            label="Bedrock Gemma 3 27B standard",
            provider_surface="aws-bedrock",
            provider="Google on Amazon Bedrock",
            service_tier="standard",
            region="us-east-1/us-east-2/us-west-2",
            input_price=0.23,
            output_price=0.38,
            capability_tier="cheap-general",
            roles=("classifier", "runbook selector", "simple draft"),
            supports_flex=False,
            price_source=BEDROCK_PRICING_SOURCE,
            availability_notes="Cheap general-purpose row for US Bedrock regions.",
        ),
        _catalog_entry(
            route_id="bedrock_nemotron_nano_2_standard_us",
            model="nvidia.nemotron-nano-2",
            label="Bedrock NVIDIA Nemotron Nano 2 standard",
            provider_surface="aws-bedrock",
            provider="NVIDIA on Amazon Bedrock",
            service_tier="standard",
            region="us-east-1/us-east-2/us-west-2",
            input_price=0.06,
            output_price=0.23,
            capability_tier="cheap-classifier",
            roles=("watch-loop scorer", "cheap triage", "classification"),
            supports_flex=False,
            price_source=BEDROCK_PRICING_SOURCE,
            availability_notes="Very low-cost US Bedrock scout lane.",
        ),
        _catalog_entry(
            route_id="bedrock_minimax_m2_5_standard_us",
            model="minimax.m2-5",
            label="Bedrock MiniMax M2.5 standard",
            provider_surface="aws-bedrock",
            provider="MiniMax on Amazon Bedrock",
            service_tier="standard",
            region="us-east-1/us-east-2/us-west-2",
            input_price=0.30,
            output_price=1.20,
            capability_tier="synthesis-scout",
            roles=("draft resolver", "summarizer", "compare lane"),
            supports_flex=False,
            price_source=BEDROCK_PRICING_SOURCE,
            availability_notes="US standard row; useful as a non-frontier compare lane.",
        ),
        _catalog_entry(
            route_id="bedrock_mistral_large_3_standard_us",
            model="mistral.large-3",
            label="Bedrock Mistral Large 3 standard",
            provider_surface="aws-bedrock",
            provider="Mistral on Amazon Bedrock",
            service_tier="standard",
            region="us-east-1/us-east-2/us-west-2",
            input_price=0.50,
            output_price=1.50,
            capability_tier="general-scout",
            roles=("draft resolver", "workflow analysis", "compare lane"),
            supports_flex=False,
            price_source=BEDROCK_PRICING_SOURCE,
            availability_notes="US standard row; Flex discount exists by provider note.",
        ),
    )


def _catalog_cost_usd(
    entry: ModelCatalogEntry,
    *,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
) -> float:
    cached_tokens = max(0, min(input_tokens, cached_input_tokens))
    uncached_tokens = max(0, input_tokens - cached_tokens)
    cached_price = (
        entry.input_usd_per_1m
        if entry.cached_input_usd_per_1m is None
        else entry.cached_input_usd_per_1m
    )
    return round(
        uncached_tokens / 1_000_000 * entry.input_usd_per_1m
        + cached_tokens / 1_000_000 * cached_price
        + output_tokens / 1_000_000 * entry.output_usd_per_1m,
        6,
    )


def _ticket_token_totals(tickets: list[TicketShape]) -> dict[str, int]:
    return {
        "input_tokens": sum(ticket.input_tokens for ticket in tickets),
        "cached_input_tokens": sum(ticket.cached_input_tokens for ticket in tickets),
        "output_tokens": sum(ticket.output_tokens for ticket in tickets),
    }


def _triage_token_totals(tickets: list[TicketShape]) -> dict[str, int]:
    input_tokens = 0
    cached_tokens = 0
    output_tokens = 0
    for ticket in tickets:
        triage_input = min(12_000, max(2_000, _scaled(ticket.input_tokens, 0.12)))
        input_tokens += triage_input
        cached_tokens += min(triage_input, _scaled(ticket.cached_input_tokens, 0.12))
        output_tokens += min(900, max(300, _scaled(ticket.output_tokens, 0.18)))
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
    }


def _helpdesk_token_totals(case_limit: int) -> dict[str, int]:
    cases = list(HELP_DESK_CASES[: case_limit or DEFAULT_HELPDESK_BENCHMARK_CASES])
    return {
        "input_tokens": sum(case.input_tokens for case in cases),
        "cached_input_tokens": sum(case.cached_input_tokens for case in cases),
        "output_tokens": sum(case.output_tokens for case in cases),
    }


def build_model_capability_price_matrix(
    *,
    tickets: list[TicketShape],
    max_do: int,
    helpdesk_case_count: int,
) -> dict[str, Any]:
    safe_tickets = _select_safe(tickets, max_do)
    full_safe_shape = _ticket_token_totals(safe_tickets)
    triage_shape = _triage_token_totals(tickets)
    helpdesk_shape = _helpdesk_token_totals(helpdesk_case_count)
    sample_shape = {
        "input_tokens": 100_000,
        "cached_input_tokens": 20_000,
        "output_tokens": 5_000,
    }

    rows: list[dict[str, Any]] = []
    for entry in model_catalog_entries():
        row = asdict(entry)
        row.update(
            {
                "sample_ticket_usd": _catalog_cost_usd(entry, **sample_shape),
                "triage_all_tickets_usd": _catalog_cost_usd(entry, **triage_shape),
                "full_safe_tickets_usd": _catalog_cost_usd(entry, **full_safe_shape),
                "helpdesk_cases_usd": _catalog_cost_usd(entry, **helpdesk_shape),
            }
        )
        rows.append(row)

    by_route = {str(row["route_id"]): row for row in rows}
    base_flex = float(by_route["openai_direct_gpt_5_5_flex"]["full_safe_tickets_usd"])
    base_fast = float(
        by_route["openai_direct_gpt_5_5_priority"]["full_safe_tickets_usd"]
    )
    sample_fast = float(by_route["openai_direct_gpt_5_5_priority"]["sample_ticket_usd"])
    helpdesk_fast = float(
        by_route["openai_direct_gpt_5_5_priority"]["helpdesk_cases_usd"]
    )
    base_bedrock = float(
        by_route["bedrock_openai_gpt_5_5_ondemand_us_east_2"]["full_safe_tickets_usd"]
    )
    for row in rows:
        full_safe = float(row["full_safe_tickets_usd"])
        sample = float(row["sample_ticket_usd"])
        helpdesk = float(row["helpdesk_cases_usd"])
        row["full_safe_ratio_vs_openai_5_5_flex"] = (
            round(full_safe / base_flex, 4) if base_flex else 0.0
        )
        row["sample_ticket_cost_percent_vs_frontier_fast"] = (
            round(sample / sample_fast * 100, 2) if sample_fast else 0.0
        )
        row["full_safe_cost_percent_vs_frontier_fast"] = (
            round(full_safe / base_fast * 100, 2) if base_fast else 0.0
        )
        row["full_safe_savings_percent_vs_frontier_fast"] = (
            round((1.0 - full_safe / base_fast) * 100, 2) if base_fast else 0.0
        )
        row["helpdesk_cost_percent_vs_frontier_fast"] = (
            round(helpdesk / helpdesk_fast * 100, 2) if helpdesk_fast else 0.0
        )
        row["full_safe_ratio_vs_bedrock_5_5_ondemand"] = (
            round(full_safe / base_bedrock, 4) if base_bedrock else 0.0
        )

    cheapest_full_safe = min(rows, key=lambda row: float(row["full_safe_tickets_usd"]))
    cheapest_frontier = min(
        (
            row
            for row in rows
            if str(row["capability_tier"]).startswith(("frontier", "strong"))
        ),
        key=lambda row: float(row["full_safe_tickets_usd"]),
    )
    return {
        "schema": "norman.gaphelp-model-capability-price-matrix.v1",
        "source_checked_on": "2026-06-13",
        "pricing_sources": {
            "openai": OPENAI_PRICING_SOURCE,
            "bedrock": BEDROCK_PRICING_SOURCE,
            "bedrock_gpt_oss_20b": BEDROCK_GPT_OSS_20B_SOURCE,
            "bedrock_gpt_oss_120b": BEDROCK_GPT_OSS_120B_SOURCE,
            "bedrock_kimi_k2_5": BEDROCK_KIMI_K2_5_SOURCE,
        },
        "operation_shapes": {
            "sample_ticket": sample_shape,
            "triage_all_tickets": triage_shape,
            "full_safe_tickets": full_safe_shape,
            "helpdesk_cases": helpdesk_shape,
        },
        "cost_baselines": {
            "openai_5_5_frontier_fast_100": {
                "route_id": "openai_direct_gpt_5_5_priority",
                "label": "OpenAI GPT-5.5 priority fast",
                "interpretation": (
                    "100% means the modeled token cost of the OpenAI GPT-5.5 "
                    "Frontier Fast/Priority lane for the same operation shape. "
                    "Lower percentages are cheaper, not automatically equivalent "
                    "quality."
                ),
                "sample_ticket_usd": sample_fast,
                "full_safe_tickets_usd": base_fast,
                "helpdesk_cases_usd": helpdesk_fast,
            }
        },
        "model_count": len(rows),
        "rows": sorted(rows, key=lambda row: float(row["full_safe_tickets_usd"])),
        "findings": {
            "frontier_fast_cost_baseline": (
                "OpenAI GPT-5.5 priority fast is the 100% cost baseline; "
                "matrix rows show percent-of-fast and savings for the same token "
                "operation shape."
            ),
            "bedrock_gpt_5_4_vs_5_5": (
                "Bedrock GPT-5.4 is modeled at 0.50x GPT-5.5 for input, "
                "cached input, and output."
            ),
            "frontier_bedrock_tier": (
                "Bedrock GPT-5.5/GPT-5.4 frontier rows are on-demand; "
                "gpt-oss/Qwen rows expose Flex/Batch in the public AWS price table."
            ),
            "cheapest_full_safe_route": cheapest_full_safe["route_id"],
            "cheapest_frontier_or_strong_route": cheapest_frontier["route_id"],
            "fast_routes": [
                row["route_id"] for row in rows if row.get("latency_class") == "fast"
            ],
            "kimi_route": "bedrock_moonshot_kimi_k2_5_standard_us"
            if "bedrock_moonshot_kimi_k2_5_standard_us" in by_route
            else "",
            "warning": (
                "Capability is not interchangeable. Cheap scout rows should route "
                "triage/drafts and still escalate low-confidence or high-risk closes."
            ),
        },
    }


CONTROL_PLANE_ISSUE_CLASSES: tuple[ControlPlaneIssueClass, ...] = (
    ControlPlaneIssueClass(
        issue_id="watch_status_inventory",
        label="Watch status / inventory only",
        examples=("poll /api/status", "count BBS handoffs", "detect changed tickets"),
        authority_level="none",
        required_quality=0.10,
        target_operational_accuracy=0.99,
        target_strict_accuracy=0.99,
        max_overreach_risk=0.01,
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        requires_tools=False,
        requires_final_close_authority=False,
        requires_frontier_verifier=False,
        local_only_allowed=True,
        notes="Should stay deterministic/local; model calls are waste.",
    ),
    ControlPlaneIssueClass(
        issue_id="operator_status_answer",
        label="Operator status answer",
        examples=(
            "answer what are you working on",
            "summarize last reply, queue, and current plan",
            "explain blocked/waiting state without starting new work",
        ),
        authority_level="mouth",
        required_quality=0.58,
        target_operational_accuracy=0.92,
        target_strict_accuracy=0.86,
        max_overreach_risk=0.04,
        input_tokens=28_000,
        cached_input_tokens=10_000,
        output_tokens=1_100,
        requires_tools=True,
        requires_final_close_authority=False,
        requires_frontier_verifier=False,
        notes="Cheap model can narrate deterministic status facts; no new work should be launched.",
    ),
    ControlPlaneIssueClass(
        issue_id="queued_prompt_or_interrupt_control",
        label="Queued prompt / interruption control",
        examples=(
            "remove queued prompt",
            "upgrade queued prompt to interruption",
            "recover staged prompt after restart",
        ),
        authority_level="mouth",
        required_quality=0.70,
        target_operational_accuracy=0.94,
        target_strict_accuracy=0.89,
        max_overreach_risk=0.035,
        input_tokens=46_000,
        cached_input_tokens=16_000,
        output_tokens=1_900,
        requires_tools=True,
        requires_final_close_authority=False,
        requires_frontier_verifier=False,
        notes="Model may recommend wait/remove/interrupt; UI action remains deterministic and visible.",
    ),
    ControlPlaneIssueClass(
        issue_id="undo_or_unwind_request",
        label="Undo / unwind request",
        examples=(
            "undo the latest turn",
            "remove the last local reply",
            "explain rollback boundary after external write",
        ),
        authority_level="seal",
        required_quality=0.88,
        target_operational_accuracy=0.96,
        target_strict_accuracy=0.93,
        max_overreach_risk=0.018,
        input_tokens=112_000,
        cached_input_tokens=38_000,
        output_tokens=4_100,
        requires_tools=True,
        requires_final_close_authority=True,
        requires_frontier_verifier=False,
        notes="Local unwind is narrow; external undo needs a 5.4-checked plan and operator approval.",
    ),
    ControlPlaneIssueClass(
        issue_id="ticket_bucket_and_dedupe",
        label="Ticket bucket, dedupe, and obvious routing",
        examples=(
            "classify GAPHELP queue",
            "identify stale duplicate",
            "pick owner lane",
        ),
        authority_level="mouth",
        required_quality=0.50,
        target_operational_accuracy=0.90,
        target_strict_accuracy=0.84,
        max_overreach_risk=0.06,
        input_tokens=18_000,
        cached_input_tokens=6_000,
        output_tokens=900,
        requires_tools=False,
        requires_final_close_authority=False,
        requires_frontier_verifier=False,
        notes="Cheap classifiers are acceptable if they abstain on ambiguity.",
    ),
    ControlPlaneIssueClass(
        issue_id="clear_runbook_selection",
        label="Clear help-desk runbook selection",
        examples=("missing price", "missing product", "report download failure"),
        authority_level="mouth",
        required_quality=0.62,
        target_operational_accuracy=0.92,
        target_strict_accuracy=0.87,
        max_overreach_risk=0.05,
        input_tokens=42_000,
        cached_input_tokens=14_000,
        output_tokens=1_700,
        requires_tools=False,
        requires_final_close_authority=False,
        requires_frontier_verifier=False,
        notes="The model only routes and drafts evidence terms; it does not mutate tickets.",
    ),
    ControlPlaneIssueClass(
        issue_id="safe_low_risk_ticket_draft",
        label="Safe low-risk ticket draft",
        examples=(
            "customer-safe summary",
            "preflight-only cleanup plan",
            "readonly evidence packet",
        ),
        authority_level="mouth",
        required_quality=0.72,
        target_operational_accuracy=0.93,
        target_strict_accuracy=0.88,
        max_overreach_risk=0.04,
        input_tokens=86_000,
        cached_input_tokens=24_000,
        output_tokens=3_800,
        requires_tools=False,
        requires_final_close_authority=False,
        requires_frontier_verifier=False,
        notes="Can be drafted by cheaper lanes when final close remains gated.",
    ),
    ControlPlaneIssueClass(
        issue_id="bbs_coordination_decision",
        label="BBS coordination decision",
        examples=("fork vs block", "do-not-ACK semantics", "owner handoff summary"),
        authority_level="mouth",
        required_quality=0.76,
        target_operational_accuracy=0.94,
        target_strict_accuracy=0.90,
        max_overreach_risk=0.03,
        input_tokens=54_000,
        cached_input_tokens=18_000,
        output_tokens=2_400,
        requires_tools=False,
        requires_final_close_authority=False,
        requires_frontier_verifier=False,
        notes="Wrong answers create coordination churn; require exact ownership semantics.",
    ),
    ControlPlaneIssueClass(
        issue_id="kpi_exec_summary",
        label="KPI executive summary from structured outputs",
        examples=(
            "weekly KPI 3 bullets",
            "known report path",
            "dashboard delta summary",
        ),
        authority_level="mouth",
        required_quality=0.78,
        target_operational_accuracy=0.94,
        target_strict_accuracy=0.89,
        max_overreach_risk=0.03,
        input_tokens=180_000,
        cached_input_tokens=120_000,
        output_tokens=3_000,
        requires_tools=False,
        requires_final_close_authority=False,
        requires_frontier_verifier=False,
        notes="If deterministic KPI extraction is local, the model only writes the executive summary.",
    ),
    ControlPlaneIssueClass(
        issue_id="leaf_code_patch_with_tests",
        label="Leaf code patch with test evidence",
        examples=(
            "small benchmark patch",
            "single-file parser fix",
            "focused unit tests",
        ),
        authority_level="seal",
        required_quality=0.82,
        target_operational_accuracy=0.95,
        target_strict_accuracy=0.92,
        max_overreach_risk=0.025,
        input_tokens=130_000,
        cached_input_tokens=40_000,
        output_tokens=6_000,
        requires_tools=True,
        requires_final_close_authority=True,
        requires_frontier_verifier=False,
        notes="Needs tool discipline and test proof; cheap coder lanes may draft only.",
    ),
    ControlPlaneIssueClass(
        issue_id="exact_numeric_or_revenue_reconcile",
        label="Exact numeric/revenue reconciliation",
        examples=("multi-table totals", "invoice mismatch", "KPI arithmetic proof"),
        authority_level="purse",
        required_quality=0.86,
        target_operational_accuracy=0.96,
        target_strict_accuracy=0.94,
        max_overreach_risk=0.02,
        input_tokens=220_000,
        cached_input_tokens=80_000,
        output_tokens=5_600,
        requires_tools=True,
        requires_final_close_authority=True,
        requires_frontier_verifier=True,
        notes="Best shape is deterministic compute plus model explanation; pure model math should be verified.",
    ),
    ControlPlaneIssueClass(
        issue_id="cross_lane_ambiguous_ticket",
        label="Cross-lane ambiguous ticket",
        examples=(
            "mixed owner scope",
            "research + deploy + customer message",
            "stale BBS state",
        ),
        authority_level="seal",
        required_quality=0.90,
        target_operational_accuracy=0.96,
        target_strict_accuracy=0.93,
        max_overreach_risk=0.02,
        input_tokens=260_000,
        cached_input_tokens=80_000,
        output_tokens=7_500,
        requires_tools=False,
        requires_final_close_authority=True,
        requires_frontier_verifier=True,
        notes="Abstention and escalation are part of correctness.",
    ),
    ControlPlaneIssueClass(
        issue_id="deploy_cloud_or_netops_change",
        label="Deploy/cloud/NetOps change plan",
        examples=("restart canary", "Bedrock route migration", "network allow-list"),
        authority_level="sword",
        required_quality=0.92,
        target_operational_accuracy=0.97,
        target_strict_accuracy=0.95,
        max_overreach_risk=0.015,
        input_tokens=240_000,
        cached_input_tokens=70_000,
        output_tokens=8_000,
        requires_tools=True,
        requires_final_close_authority=True,
        requires_frontier_verifier=True,
        notes="Execution still requires approval; model can produce plan/evidence only.",
    ),
)


FOUNDATIONAL_SKILL_CASES: tuple[FoundationalSkillCase, ...] = (
    FoundationalSkillCase(
        skill_id="local_status_inventory",
        label="Local status and inventory watch",
        family="local",
        examples=("poll /api/status", "count queue depth", "read BBS summary"),
        required_quality=0.10,
        target_operational_accuracy=0.99,
        target_strict_accuracy=0.99,
        max_overreach_risk=0.005,
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        local_only_allowed=True,
        notes="No model call should be made; this is pure local control-plane plumbing.",
    ),
    FoundationalSkillCase(
        skill_id="tui_operator_status_answer",
        label="TUI operator status answer",
        family="synthesis",
        examples=(
            "answer what are you working on",
            "summarize current state, queue depth, last reply, and plan estimate",
            "report waiting/blocked state without creating new work",
        ),
        required_quality=0.60,
        target_operational_accuracy=0.92,
        target_strict_accuracy=0.86,
        max_overreach_risk=0.04,
        input_tokens=24_000,
        cached_input_tokens=9_000,
        output_tokens=1_200,
        requires_tools=True,
        notes="Use deterministic status snapshot first; cheap Bedrock worker can turn it into operator language.",
    ),
    FoundationalSkillCase(
        skill_id="tui_working_on_plan_estimate",
        label="Working-on recap and plan estimate",
        family="execution_plan",
        examples=(
            "recite the planner-understood task in proper terms",
            "estimate skills, tools, timing, and model spend",
            "log initial vs planned vs final estimates",
        ),
        required_quality=0.74,
        target_operational_accuracy=0.94,
        target_strict_accuracy=0.89,
        max_overreach_risk=0.03,
        input_tokens=42_000,
        cached_input_tokens=16_000,
        output_tokens=1_800,
        requires_tools=True,
        notes="Good cheap-worker target when the estimate is advisory and logged.",
    ),
    FoundationalSkillCase(
        skill_id="tui_queue_interrupt_recovery",
        label="Queue, interrupt, and staged prompt recovery",
        family="runbook",
        examples=(
            "choose wait vs remove queued prompt",
            "upgrade queued prompt to interruption",
            "recover a prompt that left the composer after restart",
        ),
        required_quality=0.72,
        target_operational_accuracy=0.94,
        target_strict_accuracy=0.89,
        max_overreach_risk=0.035,
        input_tokens=44_000,
        cached_input_tokens=15_000,
        output_tokens=1_900,
        requires_tools=True,
        notes="Model recommends the UI path; the actual queue mutation should stay an explicit UI action.",
    ),
    FoundationalSkillCase(
        skill_id="tui_safe_undo_or_unwind_gate",
        label="Safe undo/unwind gate",
        family="execution_plan",
        examples=(
            "undo latest local turn",
            "explain what cannot be unwound after a live write",
            "produce rollback checklist before touching external state",
        ),
        required_quality=0.88,
        target_operational_accuracy=0.965,
        target_strict_accuracy=0.935,
        max_overreach_risk=0.016,
        input_tokens=108_000,
        cached_input_tokens=36_000,
        output_tokens=4_000,
        requires_tools=True,
        requires_state_change=True,
        requires_5_4_heavy_lift=True,
        notes="Do not let small models decide undo authority; they can gather facts before the 5.4 gate.",
    ),
    FoundationalSkillCase(
        skill_id="tui_bbs_close_loop_decision",
        label="BBS close-loop decision",
        family="governance",
        examples=(
            "owner ACK vs coordinator fork",
            "mark BLOCKED with exact blocker",
            "close DONE only with clear completion evidence",
        ),
        required_quality=0.84,
        target_operational_accuracy=0.96,
        target_strict_accuracy=0.93,
        max_overreach_risk=0.02,
        input_tokens=66_000,
        cached_input_tokens=24_000,
        output_tokens=2_700,
        requires_tools=True,
        requires_high_authority=True,
        notes="Cheap model may summarize BBS state; 5.4 checks ACK semantics before any write.",
    ),
    FoundationalSkillCase(
        skill_id="tui_tenant_purse_route_check",
        label="Tenant, purse, and route policy check",
        family="governance",
        examples=(
            "work-special vs personal TUI",
            "Bedrock-first work route",
            "stop before purse-affecting provider default change",
        ),
        required_quality=0.90,
        target_operational_accuracy=0.97,
        target_strict_accuracy=0.945,
        max_overreach_risk=0.014,
        input_tokens=82_000,
        cached_input_tokens=30_000,
        output_tokens=3_200,
        requires_tools=True,
        requires_high_authority=True,
        requires_5_4_heavy_lift=True,
        notes="This is a prompt/tooling policy check for all TUIs; final spend/default changes remain approval-gated.",
    ),
    FoundationalSkillCase(
        skill_id="tui_context_resume_handoff",
        label="Context resume and handoff digest",
        family="retrieval",
        examples=(
            "find compact prior state",
            "separate durable facts from stale memory refs",
            "prepare handoff without leaking tenant data",
        ),
        required_quality=0.68,
        target_operational_accuracy=0.93,
        target_strict_accuracy=0.88,
        max_overreach_risk=0.035,
        input_tokens=54_000,
        cached_input_tokens=22_000,
        output_tokens=2_100,
        requires_tools=True,
        notes="Lower models can retrieve and summarize when tenant labels and redaction checks are deterministic.",
    ),
    FoundationalSkillCase(
        skill_id="tui_session_to_runbook_promotion",
        label="Session-to-runbook promotion",
        family="governance",
        examples=(
            "find repeated workflow in old sessions",
            "draft skill/runbook/tool candidates",
            "require validators before promotion",
        ),
        required_quality=0.82,
        target_operational_accuracy=0.955,
        target_strict_accuracy=0.92,
        max_overreach_risk=0.022,
        input_tokens=96_000,
        cached_input_tokens=38_000,
        output_tokens=3_900,
        requires_tools=True,
        requires_5_4_heavy_lift=True,
        notes="Cheap extraction is useful, but 5.4 should review risk tier and tenant boundary before promotion.",
    ),
    FoundationalSkillCase(
        skill_id="tenant_domain_owner_classification",
        label="Tenant/domain/owner classification",
        family="classification",
        examples=(
            "work-special vs personal ticket",
            "expected TUI owner",
            "cross-boundary handoff",
        ),
        required_quality=0.62,
        target_operational_accuracy=0.91,
        target_strict_accuracy=0.86,
        max_overreach_risk=0.045,
        input_tokens=9_000,
        cached_input_tokens=2_000,
        output_tokens=550,
        notes="Cheap classifier is acceptable only if uncertainty routes to handoff.",
    ),
    FoundationalSkillCase(
        skill_id="right_data_artifact_lookup",
        label="Find the right local data/artifact",
        family="retrieval",
        examples=(
            "choose status DB vs registry",
            "find benchmark artifact",
            "select source log path",
        ),
        required_quality=0.66,
        target_operational_accuracy=0.92,
        target_strict_accuracy=0.87,
        max_overreach_risk=0.04,
        input_tokens=18_000,
        cached_input_tokens=6_000,
        output_tokens=900,
        requires_tools=True,
        notes="Tests whether a small model can locate the right evidence before synthesis.",
    ),
    FoundationalSkillCase(
        skill_id="simple_structured_data_operation",
        label="Simple JSON/SQLite/JQ data operation",
        family="data",
        examples=("extract a row", "summarize counts", "compare two status payloads"),
        required_quality=0.68,
        target_operational_accuracy=0.93,
        target_strict_accuracy=0.89,
        max_overreach_risk=0.035,
        input_tokens=24_000,
        cached_input_tokens=8_000,
        output_tokens=1_100,
        requires_tools=True,
        notes="Should prefer deterministic tools with a cheap model selecting fields.",
    ),
    FoundationalSkillCase(
        skill_id="simple_code_patch_or_parser_fix",
        label="Simple code/parser patch with focused tests",
        family="code",
        examples=("one parser fix", "small benchmark column", "unit-test update"),
        required_quality=0.83,
        target_operational_accuracy=0.95,
        target_strict_accuracy=0.91,
        max_overreach_risk=0.025,
        input_tokens=54_000,
        cached_input_tokens=18_000,
        output_tokens=3_200,
        requires_tools=True,
        requires_code=True,
        notes="Cheap coder lanes may draft; final acceptance still needs test proof.",
    ),
    FoundationalSkillCase(
        skill_id="single_runbook_step_no_state_change",
        label="Single runbook step, no state change",
        family="runbook",
        examples=("classify runbook", "gather evidence terms", "produce dry-run plan"),
        required_quality=0.78,
        target_operational_accuracy=0.94,
        target_strict_accuracy=0.90,
        max_overreach_risk=0.03,
        input_tokens=38_000,
        cached_input_tokens=14_000,
        output_tokens=1_900,
        notes="Good target for GPT OSS 120B or similar scout lanes.",
    ),
    FoundationalSkillCase(
        skill_id="safe_customer_or_operator_draft",
        label="Safe customer/operator draft",
        family="synthesis",
        examples=("customer-safe update", "operator checkpoint", "ticket note draft"),
        required_quality=0.77,
        target_operational_accuracy=0.94,
        target_strict_accuracy=0.89,
        max_overreach_risk=0.03,
        input_tokens=44_000,
        cached_input_tokens=16_000,
        output_tokens=2_400,
        notes="Draft-only; cheap synthesis lanes should not claim resolution.",
    ),
    FoundationalSkillCase(
        skill_id="multi_source_root_cause_synthesis",
        label="Multi-source root-cause synthesis",
        family="synthesis",
        examples=("combine status, logs, BBS, and runbook", "explain likely blocker"),
        required_quality=0.86,
        target_operational_accuracy=0.95,
        target_strict_accuracy=0.92,
        max_overreach_risk=0.025,
        input_tokens=96_000,
        cached_input_tokens=38_000,
        output_tokens=4_200,
        requires_tools=True,
        requires_5_4_heavy_lift=True,
        notes="This is where Bedrock GPT-5.4 high/xhigh should do heavy lifting.",
    ),
    FoundationalSkillCase(
        skill_id="approval_boundary_detection",
        label="Approval boundary detection",
        family="governance",
        examples=("purse/seal/sword boundary", "stop before restart", "ask approval"),
        required_quality=0.90,
        target_operational_accuracy=0.97,
        target_strict_accuracy=0.94,
        max_overreach_risk=0.015,
        input_tokens=62_000,
        cached_input_tokens=24_000,
        output_tokens=2_600,
        requires_high_authority=True,
        notes="Bedrock GPT-5.4 xhigh should usually be enough; escalate on ambiguity.",
    ),
    FoundationalSkillCase(
        skill_id="tenant_boundary_and_data_isolation",
        label="Tenant boundary and data isolation",
        family="governance",
        examples=(
            "OpenBrand work vs personal",
            "wrong execution surface",
            "cross-domain ticket redirect",
        ),
        required_quality=0.92,
        target_operational_accuracy=0.97,
        target_strict_accuracy=0.95,
        max_overreach_risk=0.012,
        input_tokens=74_000,
        cached_input_tokens=28_000,
        output_tokens=3_000,
        requires_high_authority=True,
        notes="This should be explicit in prompts and checked before runbook execution.",
    ),
    FoundationalSkillCase(
        skill_id="state_change_execution_plan",
        label="State-change execution plan",
        family="execution_plan",
        examples=("restart plan", "deploy plan", "network/DNS/cloud change plan"),
        required_quality=0.93,
        target_operational_accuracy=0.97,
        target_strict_accuracy=0.95,
        max_overreach_risk=0.012,
        input_tokens=128_000,
        cached_input_tokens=42_000,
        output_tokens=5_400,
        requires_tools=True,
        requires_state_change=True,
        requires_high_authority=True,
        notes="5.4 xhigh can prepare the plan; execution remains approval-gated.",
    ),
    FoundationalSkillCase(
        skill_id="high_authority_final_decision",
        label="High-authority final decision",
        family="final_verifier",
        examples=(
            "close high-risk ticket",
            "approve deploy recommendation",
            "resolve ambiguous owner",
        ),
        required_quality=0.96,
        target_operational_accuracy=0.985,
        target_strict_accuracy=0.97,
        max_overreach_risk=0.008,
        input_tokens=156_000,
        cached_input_tokens=56_000,
        output_tokens=5_800,
        requires_tools=True,
        requires_state_change=True,
        requires_high_authority=True,
        requires_5_5_verifier=True,
        notes="This is the narrow lane where Bedrock GPT-5.5 xhigh should be used.",
    ),
)


TUI_OPERATOR_WORKFLOW_SKILL_IDS: tuple[str, ...] = (
    "local_status_inventory",
    "tui_operator_status_answer",
    "tui_working_on_plan_estimate",
    "tui_queue_interrupt_recovery",
    "tui_safe_undo_or_unwind_gate",
    "tui_bbs_close_loop_decision",
    "tui_tenant_purse_route_check",
    "tui_context_resume_handoff",
    "tui_session_to_runbook_promotion",
    "tenant_domain_owner_classification",
    "approval_boundary_detection",
)


def threshold_candidate_profiles() -> tuple[CandidateThresholdProfile, ...]:
    return (
        CandidateThresholdProfile(
            "local_deterministic",
            "Local deterministic/no model",
            "",
            "none",
            0.99,
            0.0,
            False,
            False,
            "ready",
            "Only valid for local-only watch/inventory work.",
        ),
        CandidateThresholdProfile(
            "bedrock_gpt_oss_20b_low",
            "Bedrock GPT OSS 20B low",
            "bedrock_gpt_oss_20b_flex_ap_southeast_2",
            "low",
            0.62,
            0.75,
            False,
            False,
            "shadow",
        ),
        CandidateThresholdProfile(
            "openai_gpt_5_4_nano_low",
            "OpenAI GPT-5.4 nano low",
            "openai_direct_gpt_5_4_nano_flex",
            "low",
            0.58,
            0.70,
            False,
            False,
            "ready",
        ),
        CandidateThresholdProfile(
            "bedrock_nemotron_nano_low",
            "Bedrock Nemotron Nano 2 low",
            "bedrock_nemotron_nano_2_standard_us",
            "low",
            0.50,
            0.70,
            False,
            False,
            "shadow",
        ),
        CandidateThresholdProfile(
            "bedrock_gemma_27b_low",
            "Bedrock Gemma 3 27B low",
            "bedrock_gemma_3_27b_standard_us",
            "low",
            0.60,
            0.78,
            False,
            False,
            "shadow",
            "Cheap first-pass classifier/summarizer; not a close authority.",
        ),
        CandidateThresholdProfile(
            "openai_gpt_5_4_mini_medium",
            "OpenAI GPT-5.4 mini medium",
            "openai_direct_gpt_5_4_mini_flex",
            "medium",
            0.74,
            1.00,
            False,
            False,
            "ready",
        ),
        CandidateThresholdProfile(
            "openai_gpt_5_4_mini_high",
            "OpenAI GPT-5.4 mini high",
            "openai_direct_gpt_5_4_mini_flex",
            "high",
            0.76,
            1.22,
            False,
            False,
            "ready",
            "Higher-effort mini lane for cheap drafts; still no final close.",
        ),
        CandidateThresholdProfile(
            "bedrock_gpt_oss_120b_medium",
            "Bedrock GPT OSS 120B medium",
            "bedrock_gpt_oss_120b_flex_ap_southeast_2",
            "medium",
            0.78,
            1.00,
            False,
            False,
            "shadow",
        ),
        CandidateThresholdProfile(
            "bedrock_gpt_oss_120b_high",
            "Bedrock GPT OSS 120B high",
            "bedrock_gpt_oss_120b_flex_ap_southeast_2",
            "high",
            0.80,
            1.22,
            False,
            False,
            "shadow",
            "Cheap high-effort scout; final close still escalates.",
        ),
        CandidateThresholdProfile(
            "bedrock_qwen3_coder_medium",
            "Bedrock Qwen3 Coder 30B medium",
            "bedrock_qwen3_coder_30b_flex_ap_southeast_2",
            "medium",
            0.72,
            1.00,
            False,
            False,
            "shadow",
        ),
        CandidateThresholdProfile(
            "bedrock_qwen3_coder_high",
            "Bedrock Qwen3 Coder 30B high",
            "bedrock_qwen3_coder_30b_flex_ap_southeast_2",
            "high",
            0.75,
            1.22,
            False,
            False,
            "shadow",
            "Candidate for code-draft scouting, not verifier acceptance.",
        ),
        CandidateThresholdProfile(
            "dgx_spark_qwen3_coder_high",
            "DGX Spark Qwen3 Coder 30B high",
            "local_dgx_spark_qwen3_coder_30b",
            "high",
            0.75,
            1.22,
            False,
            False,
            "shadow",
            "Zero marginal-cost local Spark code/data draft lane; requires validators or a frontier verifier.",
        ),
        CandidateThresholdProfile(
            "dgx_spark2_gpt_oss_120b_high",
            "DGX Spark 2x GPT OSS 120B high",
            "local_dgx_spark2_gpt_oss_120b",
            "high",
            0.80,
            1.22,
            False,
            False,
            "shadow",
            "Zero marginal-cost local Spark 2x reasoning scout; good batch/offload candidate, not final authority.",
        ),
        CandidateThresholdProfile(
            "bedrock_gemma_27b_medium",
            "Bedrock Gemma 3 27B medium",
            "bedrock_gemma_3_27b_standard_us",
            "medium",
            0.66,
            1.00,
            False,
            False,
            "shadow",
        ),
        CandidateThresholdProfile(
            "bedrock_minimax_m2_5_medium",
            "Bedrock MiniMax M2.5 medium",
            "bedrock_minimax_m2_5_standard_us",
            "medium",
            0.70,
            1.00,
            False,
            False,
            "shadow",
        ),
        CandidateThresholdProfile(
            "bedrock_mistral_large_3_medium",
            "Bedrock Mistral Large 3 medium",
            "bedrock_mistral_large_3_standard_us",
            "medium",
            0.73,
            1.00,
            False,
            False,
            "shadow",
        ),
        CandidateThresholdProfile(
            "bedrock_mistral_large_3_high",
            "Bedrock Mistral Large 3 high",
            "bedrock_mistral_large_3_standard_us",
            "high",
            0.76,
            1.22,
            False,
            False,
            "shadow",
            "Higher-effort general scout; not a final verifier.",
        ),
        CandidateThresholdProfile(
            "bedrock_deepseek_v3_2_medium",
            "Bedrock DeepSeek v3.2 medium",
            "bedrock_deepseek_v3_2_standard_us",
            "medium",
            0.76,
            1.00,
            False,
            False,
            "shadow",
        ),
        CandidateThresholdProfile(
            "bedrock_deepseek_v3_2_high",
            "Bedrock DeepSeek v3.2 high",
            "bedrock_deepseek_v3_2_standard_us",
            "high",
            0.79,
            1.22,
            False,
            False,
            "shadow",
            "Higher-effort reasoning scout; still escalates high-authority closes.",
        ),
        CandidateThresholdProfile(
            "bedrock_kimi_k2_5_medium",
            "Bedrock Kimi K2.5 medium",
            "bedrock_moonshot_kimi_k2_5_standard_us",
            "medium",
            0.80,
            1.00,
            False,
            False,
            "shadow",
            "Long-context scout lane; currently planned/offline in this TUI.",
        ),
        CandidateThresholdProfile(
            "bedrock_kimi_k2_5_high",
            "Bedrock Kimi K2.5 high",
            "bedrock_moonshot_kimi_k2_5_standard_us",
            "high",
            0.83,
            1.22,
            False,
            False,
            "shadow",
            "Good compare lane for draft/runbook reasoning; not a final close authority.",
        ),
        CandidateThresholdProfile(
            "openai_gpt_5_4_low",
            "OpenAI GPT-5.4 low",
            "openai_direct_gpt_5_4_flex",
            "low",
            0.84,
            0.82,
            False,
            False,
            "ready",
            "Cheap strong-model pass for easy tickets and drafts.",
        ),
        CandidateThresholdProfile(
            "openai_gpt_5_4_medium",
            "OpenAI GPT-5.4 medium",
            "openai_direct_gpt_5_4_flex",
            "medium",
            0.88,
            1.00,
            True,
            False,
            "ready",
        ),
        CandidateThresholdProfile(
            "openai_gpt_5_4_high",
            "OpenAI GPT-5.4 high",
            "openai_direct_gpt_5_4_flex",
            "high",
            0.91,
            1.22,
            True,
            True,
            "ready",
            "Good candidate for high-stakes verification before using 5.5.",
        ),
        CandidateThresholdProfile(
            "openai_fast_gpt_5_4_high",
            "OpenAI GPT-5.4 priority high",
            "openai_direct_gpt_5_4_priority",
            "high",
            0.91,
            1.22,
            True,
            True,
            "ready",
            "Fast/priority 5.4 lane for urgent operator-facing verification.",
        ),
        CandidateThresholdProfile(
            "bedrock_gpt_5_4_medium",
            "Bedrock GPT-5.4 medium",
            "bedrock_openai_gpt_5_4_ondemand_us_east_2",
            "medium",
            0.88,
            1.00,
            True,
            False,
            "ready",
        ),
        CandidateThresholdProfile(
            "bedrock_gpt_5_4_high",
            "Bedrock GPT-5.4 high",
            "bedrock_openai_gpt_5_4_ondemand_us_east_2",
            "high",
            0.91,
            1.22,
            True,
            True,
            "ready",
            "AWS-governed 5.4 high-effort verifier candidate.",
        ),
        CandidateThresholdProfile(
            "openai_gpt_5_4_xhigh",
            "OpenAI GPT-5.4 xhigh",
            "openai_direct_gpt_5_4_flex",
            "xhigh",
            0.94,
            1.45,
            True,
            True,
            "ready",
        ),
        CandidateThresholdProfile(
            "bedrock_gpt_5_4_xhigh",
            "Bedrock GPT-5.4 xhigh",
            "bedrock_openai_gpt_5_4_ondemand_us_east_2",
            "xhigh",
            0.94,
            1.45,
            True,
            True,
            "ready",
            "AWS-governed high-authority fallback; usually costlier than direct flex.",
        ),
        CandidateThresholdProfile(
            "openai_gpt_5_5_low",
            "OpenAI GPT-5.5 low",
            "openai_direct_gpt_5_5_flex",
            "low",
            0.91,
            0.82,
            True,
            True,
            "ready",
            "Frontier model with reduced reasoning spend.",
        ),
        CandidateThresholdProfile(
            "openai_gpt_5_5_medium",
            "OpenAI GPT-5.5 medium",
            "openai_direct_gpt_5_5_flex",
            "medium",
            0.95,
            1.00,
            True,
            True,
            "ready",
        ),
        CandidateThresholdProfile(
            "openai_gpt_5_5_high",
            "OpenAI GPT-5.5 high",
            "openai_direct_gpt_5_5_flex",
            "high",
            0.975,
            1.22,
            True,
            True,
            "ready",
            "Likely enough for most high-authority verifier passes.",
        ),
        CandidateThresholdProfile(
            "openai_gpt_5_5_xhigh",
            "OpenAI GPT-5.5 xhigh",
            "openai_direct_gpt_5_5_flex",
            "xhigh",
            0.99,
            1.45,
            True,
            True,
            "ready",
            "Reference quality baseline for this shadow matrix.",
        ),
        CandidateThresholdProfile(
            "openai_fast_gpt_5_5_medium",
            "OpenAI GPT-5.5 priority medium",
            "openai_direct_gpt_5_5_priority",
            "medium",
            0.95,
            1.00,
            True,
            True,
            "ready",
            "Fast/priority 5.5 lane; same modeled quality as direct medium at higher price.",
        ),
        CandidateThresholdProfile(
            "openai_fast_gpt_5_5_high",
            "OpenAI GPT-5.5 priority high",
            "openai_direct_gpt_5_5_priority",
            "high",
            0.975,
            1.22,
            True,
            True,
            "ready",
            "Fast/priority 5.5 lane for urgent final verification.",
        ),
        CandidateThresholdProfile(
            "openai_fast_gpt_5_5_xhigh",
            "OpenAI GPT-5.5 priority xhigh",
            "openai_direct_gpt_5_5_priority",
            "xhigh",
            0.99,
            1.45,
            True,
            True,
            "ready",
            "Highest spend lane: urgent, high-authority, operator-facing only.",
        ),
        CandidateThresholdProfile(
            "anthropic_claude_opus_4_7_high",
            "Claude Opus 4.7 high",
            "anthropic_direct_claude_opus_4_7_standard",
            "high",
            0.972,
            1.25,
            True,
            True,
            "shadow",
            "Claude Opus 4.7 comparison lane; live TUI runner receipts still needed.",
        ),
        CandidateThresholdProfile(
            "anthropic_claude_opus_4_8_high",
            "Claude Opus 4.8 high",
            "anthropic_direct_claude_opus_4_8_standard",
            "high",
            0.985,
            1.25,
            True,
            True,
            "shadow",
            "Claude Opus 4.8 default-effort comparison lane.",
        ),
        CandidateThresholdProfile(
            "anthropic_claude_opus_4_8_xhigh",
            "Claude Opus 4.8 xhigh",
            "anthropic_direct_claude_opus_4_8_standard",
            "xhigh",
            0.992,
            1.45,
            True,
            True,
            "shadow",
            "Claude Opus 4.8 high-effort comparison lane for frontier baselines.",
        ),
        CandidateThresholdProfile(
            "bedrock_gpt_5_5_medium",
            "Bedrock GPT-5.5 medium",
            "bedrock_openai_gpt_5_5_ondemand_us_east_2",
            "medium",
            0.95,
            1.00,
            True,
            True,
            "ready",
            "AWS-governed frontier medium-effort verifier.",
        ),
        CandidateThresholdProfile(
            "bedrock_gpt_5_5_high",
            "Bedrock GPT-5.5 high",
            "bedrock_openai_gpt_5_5_ondemand_us_east_2",
            "high",
            0.975,
            1.22,
            True,
            True,
            "ready",
            "AWS-governed frontier high-effort verifier.",
        ),
        CandidateThresholdProfile(
            "bedrock_gpt_5_5_xhigh",
            "Bedrock GPT-5.5 xhigh",
            "bedrock_openai_gpt_5_5_ondemand_us_east_2",
            "xhigh",
            0.99,
            1.45,
            True,
            True,
            "ready",
            "AWS-governed reference baseline; higher public token price.",
        ),
    )


def _threshold_catalog_by_route(
    model_matrix: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("route_id")): row
        for row in model_matrix.get("rows", [])
        if isinstance(row, dict)
    }


def _threshold_candidate_cost_usd(
    candidate: CandidateThresholdProfile,
    issue: ControlPlaneIssueClass,
    catalog_by_route: dict[str, dict[str, Any]],
) -> float | None:
    if candidate.candidate_id == "local_deterministic":
        return 0.0 if issue.local_only_allowed else None
    catalog = catalog_by_route.get(candidate.catalog_route_id)
    if not catalog:
        return None
    pseudo_entry = ModelCatalogEntry(
        route_id=str(catalog["route_id"]),
        model=str(catalog["model"]),
        label=str(catalog["label"]),
        provider_surface=str(catalog["provider_surface"]),
        provider=str(catalog["provider"]),
        service_tier=str(catalog["service_tier"]),
        region=str(catalog["region"]),
        input_usd_per_1m=float(catalog["input_usd_per_1m"]),
        cached_input_usd_per_1m=(
            None
            if catalog.get("cached_input_usd_per_1m") is None
            else float(catalog["cached_input_usd_per_1m"])
        ),
        output_usd_per_1m=float(catalog["output_usd_per_1m"]),
        context_window_tokens=catalog.get("context_window_tokens"),
        max_output_tokens=catalog.get("max_output_tokens"),
        capability_tier=str(catalog["capability_tier"]),
        recommended_roles=tuple(catalog.get("recommended_roles") or ()),
        supports_batch=bool(catalog.get("supports_batch")),
        supports_flex=bool(catalog.get("supports_flex")),
        supports_prompt_cache=bool(catalog.get("supports_prompt_cache")),
        supports_tools=bool(catalog.get("supports_tools")),
        price_source=str(catalog.get("price_source") or ""),
        availability_notes=str(catalog.get("availability_notes") or ""),
    )
    return _catalog_cost_usd(
        pseudo_entry,
        input_tokens=issue.input_tokens,
        cached_input_tokens=issue.cached_input_tokens,
        output_tokens=round(issue.output_tokens * candidate.output_multiplier),
    )


def _threshold_score(
    candidate: CandidateThresholdProfile,
    issue: ControlPlaneIssueClass,
    catalog_by_route: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cost = _threshold_candidate_cost_usd(candidate, issue, catalog_by_route)
    if cost is None:
        return {
            "candidate_id": candidate.candidate_id,
            "label": candidate.label,
            "cost_usd": None,
            "operational_accuracy": 0.0,
            "strict_accuracy": 0.0,
            "overreach_risk": 1.0,
            "meets_threshold": False,
            "blocked_reason": "not applicable to this issue class",
        }

    catalog = catalog_by_route.get(candidate.catalog_route_id, {})
    quality = candidate.base_quality
    if candidate.reasoning_effort == "xhigh":
        quality += 0.03
    elif candidate.reasoning_effort == "high":
        quality += 0.015
    elif candidate.reasoning_effort == "low":
        quality -= 0.02
    if issue.requires_tools and candidate.candidate_id != "local_deterministic":
        if not bool(catalog.get("supports_tools")):
            quality -= 0.08
    if issue.requires_final_close_authority and not candidate.can_final_close:
        quality -= 0.12
    if issue.requires_frontier_verifier and not candidate.can_high_authority:
        quality -= 0.18
    if issue.requires_frontier_verifier and candidate.reasoning_effort == "low":
        quality -= 0.08
    context_window = catalog.get("context_window_tokens")
    if (
        isinstance(context_window, int)
        and context_window
        and issue.input_tokens > context_window
    ):
        quality -= 0.10
    if candidate.candidate_id == "local_deterministic" and not issue.local_only_allowed:
        quality = 0.0

    margin = quality - issue.required_quality
    operational = max(
        0.0,
        min(0.995, issue.target_operational_accuracy + margin * 0.42),
    )
    strict = max(
        0.0,
        min(0.995, issue.target_strict_accuracy + margin * 0.38),
    )
    overreach = max(
        0.005,
        min(
            0.60,
            issue.max_overreach_risk
            + max(0.0, -margin) * 0.40
            - max(0.0, margin) * 0.10,
        ),
    )
    blocked_reasons: list[str] = []
    if operational < issue.target_operational_accuracy:
        blocked_reasons.append("operational_accuracy_below_target")
    if strict < issue.target_strict_accuracy:
        blocked_reasons.append("strict_accuracy_below_target")
    if overreach > issue.max_overreach_risk:
        blocked_reasons.append("overreach_risk_above_ceiling")
    if issue.requires_final_close_authority and not candidate.can_final_close:
        blocked_reasons.append("draft_only_no_final_close")
    if issue.requires_frontier_verifier and not candidate.can_high_authority:
        blocked_reasons.append("requires_frontier_verifier")
    if issue.requires_frontier_verifier and candidate.reasoning_effort == "low":
        blocked_reasons.append("low_effort_not_verifier")

    return {
        "candidate_id": candidate.candidate_id,
        "label": candidate.label,
        "catalog_route_id": candidate.catalog_route_id,
        "reasoning_effort": candidate.reasoning_effort,
        "status": candidate.status,
        "provider_surface": str(catalog.get("provider_surface") or "local"),
        "provider": str(catalog.get("provider") or "local"),
        "model": str(catalog.get("model") or "local"),
        "service_tier": str(catalog.get("service_tier") or "local"),
        "latency_class": str(catalog.get("latency_class") or "local"),
        "timing_target": str(catalog.get("timing_target") or "local"),
        "capability_tier": str(catalog.get("capability_tier") or "local"),
        "subagent_role": str(catalog.get("subagent_role") or "local"),
        "final_role": str(catalog.get("final_role") or "none"),
        "eligible_runbook_scope": str(
            catalog.get("eligible_runbook_scope") or "local only"
        ),
        "eligible_runbooks": list(catalog.get("eligible_runbooks") or ()),
        "can_final_close": candidate.can_final_close,
        "can_high_authority": candidate.can_high_authority,
        "cost_usd": round(cost, 6),
        "quality_score": round(max(0.0, min(1.0, quality)), 4),
        "operational_accuracy": round(operational, 4),
        "strict_accuracy": round(strict, 4),
        "overreach_risk": round(overreach, 4),
        "meets_threshold": not blocked_reasons,
        "blocked_reason": ", ".join(blocked_reasons),
        "notes": candidate.notes,
    }


def _foundational_candidate_cost_usd(
    candidate: CandidateThresholdProfile,
    skill: FoundationalSkillCase,
    catalog_by_route: dict[str, dict[str, Any]],
) -> float | None:
    if candidate.candidate_id == "local_deterministic":
        return 0.0 if skill.local_only_allowed else None
    catalog = catalog_by_route.get(candidate.catalog_route_id)
    if not catalog:
        return None
    pseudo_entry = ModelCatalogEntry(
        route_id=str(catalog["route_id"]),
        model=str(catalog["model"]),
        label=str(catalog["label"]),
        provider_surface=str(catalog["provider_surface"]),
        provider=str(catalog["provider"]),
        service_tier=str(catalog["service_tier"]),
        region=str(catalog["region"]),
        input_usd_per_1m=float(catalog["input_usd_per_1m"]),
        cached_input_usd_per_1m=(
            None
            if catalog.get("cached_input_usd_per_1m") is None
            else float(catalog["cached_input_usd_per_1m"])
        ),
        output_usd_per_1m=float(catalog["output_usd_per_1m"]),
        context_window_tokens=catalog.get("context_window_tokens"),
        max_output_tokens=catalog.get("max_output_tokens"),
        capability_tier=str(catalog["capability_tier"]),
        recommended_roles=tuple(catalog.get("recommended_roles") or ()),
        supports_batch=bool(catalog.get("supports_batch")),
        supports_flex=bool(catalog.get("supports_flex")),
        supports_prompt_cache=bool(catalog.get("supports_prompt_cache")),
        supports_tools=bool(catalog.get("supports_tools")),
        price_source=str(catalog.get("price_source") or ""),
        availability_notes=str(catalog.get("availability_notes") or ""),
    )
    return _catalog_cost_usd(
        pseudo_entry,
        input_tokens=skill.input_tokens,
        cached_input_tokens=skill.cached_input_tokens,
        output_tokens=round(skill.output_tokens * candidate.output_multiplier),
    )


def _candidate_text(
    candidate: CandidateThresholdProfile, catalog: dict[str, Any]
) -> str:
    return " ".join(
        str(part).lower()
        for part in (
            candidate.candidate_id,
            candidate.catalog_route_id,
            catalog.get("model", ""),
            catalog.get("capability_tier", ""),
            " ".join(str(role) for role in catalog.get("recommended_roles") or ()),
        )
    )


def _foundational_family_adjustment(
    candidate: CandidateThresholdProfile,
    skill: FoundationalSkillCase,
    catalog: dict[str, Any],
) -> float:
    text = _candidate_text(candidate, catalog)
    family = skill.family
    adjustment = 0.0
    if family == "classification":
        if "nemotron" in text or "nano" in text:
            adjustment += 0.16
        if "gemma" in text or "gpt-oss" in text:
            adjustment += 0.10
    elif family == "retrieval":
        if "gemma" in text or "gpt-oss" in text:
            adjustment += 0.10
        if "kimi" in text and bool(catalog.get("supports_tools")):
            adjustment += 0.08
        if "nemotron" in text:
            adjustment += 0.06
    elif family == "data":
        if "gpt-oss" in text or "qwen" in text:
            adjustment += 0.09
        if "gemma" in text:
            adjustment += 0.06
        if "gpt-5.4" in text or "openai.gpt-5.4" in text:
            adjustment += 0.05
    elif family == "code":
        if "qwen" in text or "coder" in text:
            adjustment += 0.14
        if "gpt-oss" in text:
            adjustment += 0.04
        if "gpt-5.4" in text or "openai.gpt-5.4" in text:
            adjustment += 0.07
    elif family == "runbook":
        if "gpt-oss-120b" in text:
            adjustment += 0.10
        elif "gpt-oss" in text:
            adjustment += 0.06
        if "gpt-5.4" in text or "openai.gpt-5.4" in text:
            adjustment += 0.06
    elif family == "synthesis":
        if any(name in text for name in ("deepseek", "mistral", "minimax", "kimi")):
            adjustment += 0.09
        if "gpt-5.4" in text or "openai.gpt-5.4" in text:
            adjustment += 0.08
    elif family == "governance":
        if "gpt-5.4" in text or "openai.gpt-5.4" in text:
            adjustment += 0.07
        if "gpt-5.5" in text or "openai.gpt-5.5" in text:
            adjustment += 0.09
    elif family == "execution_plan":
        if "gpt-5.4" in text or "openai.gpt-5.4" in text:
            adjustment += 0.08
        if "gpt-5.5" in text or "openai.gpt-5.5" in text:
            adjustment += 0.10
        if "qwen" in text or "gpt-oss" in text:
            adjustment += 0.03
    elif family == "final_verifier":
        if "gpt-5.5" in text or "openai.gpt-5.5" in text:
            adjustment += 0.10
        elif "gpt-5.4" in text or "openai.gpt-5.4" in text:
            adjustment += 0.04
    return adjustment


def _foundational_skill_score(
    candidate: CandidateThresholdProfile,
    skill: FoundationalSkillCase,
    catalog_by_route: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cost = _foundational_candidate_cost_usd(candidate, skill, catalog_by_route)
    if cost is None:
        return {
            "candidate_id": candidate.candidate_id,
            "label": candidate.label,
            "cost_usd": None,
            "operational_accuracy": 0.0,
            "strict_accuracy": 0.0,
            "overreach_risk": 1.0,
            "meets_threshold": False,
            "blocked_reason": "not applicable to this skill",
        }

    catalog = catalog_by_route.get(candidate.catalog_route_id, {})
    quality = candidate.base_quality
    if candidate.reasoning_effort == "xhigh":
        quality += 0.035
    elif candidate.reasoning_effort == "high":
        quality += 0.018
    elif candidate.reasoning_effort == "low":
        quality -= 0.018
    quality += _foundational_family_adjustment(candidate, skill, catalog)

    if candidate.candidate_id == "local_deterministic" and not skill.local_only_allowed:
        quality = 0.0
    if skill.requires_tools and candidate.candidate_id != "local_deterministic":
        if not bool(catalog.get("supports_tools")):
            quality -= 0.10
    if skill.requires_code:
        text = _candidate_text(candidate, catalog)
        if not any(name in text for name in ("coder", "qwen", "gpt-oss", "gpt-5")):
            quality -= 0.12
    if skill.requires_high_authority and not candidate.can_high_authority:
        quality -= 0.16
    if skill.requires_state_change and not candidate.can_final_close:
        quality -= 0.12
    if skill.requires_5_5_verifier:
        model = str(catalog.get("model") or "")
        if model not in {"gpt-5.5", "openai.gpt-5.5"}:
            quality -= 0.24
    context_window = catalog.get("context_window_tokens")
    if (
        isinstance(context_window, int)
        and context_window
        and skill.input_tokens > context_window
    ):
        quality -= 0.10

    margin = quality - skill.required_quality
    operational = max(
        0.0,
        min(0.995, skill.target_operational_accuracy + margin * 0.38),
    )
    strict = max(0.0, min(0.995, skill.target_strict_accuracy + margin * 0.34))
    overreach = max(
        0.003,
        min(
            0.60,
            skill.max_overreach_risk
            + max(0.0, -margin) * 0.36
            - max(0.0, margin) * 0.09,
        ),
    )

    blocked_reasons: list[str] = []
    if operational < skill.target_operational_accuracy:
        blocked_reasons.append("operational_accuracy_below_target")
    if strict < skill.target_strict_accuracy:
        blocked_reasons.append("strict_accuracy_below_target")
    if overreach > skill.max_overreach_risk:
        blocked_reasons.append("overreach_risk_above_ceiling")
    if skill.requires_high_authority and not candidate.can_high_authority:
        blocked_reasons.append("requires_high_authority_model")
    if skill.requires_state_change and not candidate.can_final_close:
        blocked_reasons.append("draft_only_no_final_close")
    if skill.requires_5_5_verifier:
        model = str(catalog.get("model") or "")
        if model not in {"gpt-5.5", "openai.gpt-5.5"}:
            blocked_reasons.append("requires_5_5_final_verifier")

    return {
        "candidate_id": candidate.candidate_id,
        "label": candidate.label,
        "catalog_route_id": candidate.catalog_route_id,
        "reasoning_effort": candidate.reasoning_effort,
        "provider_surface": str(catalog.get("provider_surface") or "local"),
        "provider": str(catalog.get("provider") or "local"),
        "model": str(catalog.get("model") or "local"),
        "service_tier": str(catalog.get("service_tier") or "local"),
        "capability_tier": str(catalog.get("capability_tier") or "local"),
        "latency_class": str(catalog.get("latency_class") or "local"),
        "supports_tools": bool(catalog.get("supports_tools")),
        "can_final_close": candidate.can_final_close,
        "can_high_authority": candidate.can_high_authority,
        "cost_usd": round(cost, 6),
        "quality_score": round(max(0.0, min(1.0, quality)), 4),
        "operational_accuracy": round(operational, 4),
        "strict_accuracy": round(strict, 4),
        "overreach_risk": round(overreach, 4),
        "meets_threshold": not blocked_reasons,
        "blocked_reason": ", ".join(blocked_reasons),
        "notes": candidate.notes,
    }


def _foundational_draft_viable(
    row: dict[str, Any], skill: FoundationalSkillCase
) -> bool:
    if row.get("cost_usd") is None:
        return False
    if row.get("candidate_id") == "local_deterministic":
        return bool(skill.local_only_allowed)
    strict_floor = max(0.0, skill.target_strict_accuracy - 0.16)
    operational_floor = max(0.0, skill.target_operational_accuracy - 0.14)
    overreach_ceiling = max(skill.max_overreach_risk * 10.0, 0.12)
    if skill.requires_code and "qwen" not in str(row.get("candidate_id")):
        if "gpt_oss" not in str(row.get("candidate_id")):
            return False
    return (
        float(row.get("strict_accuracy") or 0.0) >= strict_floor
        and float(row.get("operational_accuracy") or 0.0) >= operational_floor
        and float(row.get("overreach_risk") or 1.0) <= overreach_ceiling
    )


def _find_candidate_row(
    rows: list[dict[str, Any]], candidate_id: str
) -> dict[str, Any] | None:
    return next((row for row in rows if row.get("candidate_id") == candidate_id), None)


def _pipeline_unique_steps(steps: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for step in steps:
        if not step:
            continue
        candidate_id = str(step.get("candidate_id") or "")
        if not candidate_id or candidate_id in seen:
            continue
        seen.add(candidate_id)
        output.append(step)
    return output


def build_foundational_skill_matrix(model_matrix: dict[str, Any]) -> dict[str, Any]:
    catalog_by_route = _threshold_catalog_by_route(model_matrix)
    profiles = threshold_candidate_profiles()
    rows: list[dict[str, Any]] = []
    total_recommended = 0.0
    total_all_5_5_xhigh = 0.0
    cheap_worker_count = 0
    local_only_count = 0
    bedrock_5_4_heavy_count = 0
    bedrock_5_5_final_count = 0

    for skill in FOUNDATIONAL_SKILL_CASES:
        candidate_rows = [
            _foundational_skill_score(profile, skill, catalog_by_route)
            for profile in profiles
        ]
        passing = [
            row
            for row in candidate_rows
            if row.get("meets_threshold") and row.get("cost_usd") is not None
        ]
        bedrock_passing = [
            row for row in passing if row.get("provider_surface") == "aws-bedrock"
        ]
        minimum_any = min(passing, key=_candidate_cost_sort) if passing else None
        minimum_bedrock = (
            min(bedrock_passing, key=_candidate_cost_sort) if bedrock_passing else None
        )
        bedrock_rows = [
            row
            for row in candidate_rows
            if row.get("provider_surface") == "aws-bedrock"
            and row.get("cost_usd") is not None
        ]
        draft_pool = [
            row
            for row in bedrock_rows
            if _foundational_draft_viable(row, skill)
            and not str(row.get("candidate_id", "")).startswith("bedrock_gpt_5_5")
        ]
        draft_worker = (
            min(draft_pool, key=_candidate_cost_sort) if draft_pool else minimum_bedrock
        )
        bedrock_5_4_xhigh = _find_candidate_row(candidate_rows, "bedrock_gpt_5_4_xhigh")
        bedrock_5_5_xhigh = _find_candidate_row(candidate_rows, "bedrock_gpt_5_5_xhigh")

        if skill.local_only_allowed:
            pipeline_steps = [minimum_any]
            local_only_count += 1
        elif skill.requires_5_5_verifier:
            pipeline_steps = [bedrock_5_4_xhigh, bedrock_5_5_xhigh]
            bedrock_5_5_final_count += 1
            bedrock_5_4_heavy_count += 1
        elif (
            skill.requires_5_4_heavy_lift
            or skill.requires_high_authority
            or skill.requires_state_change
        ):
            pipeline_steps = [bedrock_5_4_xhigh]
            bedrock_5_4_heavy_count += 1
        else:
            pipeline_steps = [minimum_bedrock or minimum_any]
        pipeline = _pipeline_unique_steps(pipeline_steps)
        pipeline_cost = round(
            sum(float(step.get("cost_usd") or 0.0) for step in pipeline), 6
        )
        all_5_5_cost = float((bedrock_5_5_xhigh or {}).get("cost_usd") or 0.0)
        total_recommended += pipeline_cost
        total_all_5_5_xhigh += all_5_5_cost
        if any(
            step.get("provider_surface") == "aws-bedrock"
            and not str(step.get("candidate_id", "")).startswith("bedrock_gpt_5")
            for step in pipeline
        ):
            cheap_worker_count += 1

        rows.append(
            {
                "skill_id": skill.skill_id,
                "label": skill.label,
                "family": skill.family,
                "examples": list(skill.examples),
                "targets": {
                    "operational_accuracy": skill.target_operational_accuracy,
                    "strict_accuracy": skill.target_strict_accuracy,
                    "max_overreach_risk": skill.max_overreach_risk,
                },
                "token_shape": {
                    "input_tokens": skill.input_tokens,
                    "cached_input_tokens": skill.cached_input_tokens,
                    "output_tokens": skill.output_tokens,
                },
                "minimum_any": minimum_any,
                "minimum_bedrock": minimum_bedrock,
                "draft_worker": draft_worker,
                "bedrock_5_4_xhigh_heavy_lift": bedrock_5_4_xhigh,
                "bedrock_5_5_xhigh_final": bedrock_5_5_xhigh,
                "recommended_pipeline": pipeline,
                "recommended_pipeline_cost_usd": pipeline_cost,
                "all_bedrock_5_5_xhigh_cost_usd": round(all_5_5_cost, 6),
                "savings_vs_all_bedrock_5_5_xhigh": (
                    round(1.0 - pipeline_cost / all_5_5_cost, 4)
                    if all_5_5_cost
                    else 0.0
                ),
                "candidate_rows": sorted(candidate_rows, key=_candidate_cost_sort),
                "requires_5_4_heavy_lift": skill.requires_5_4_heavy_lift,
                "requires_5_5_verifier": skill.requires_5_5_verifier,
                "notes": skill.notes,
            }
        )

    savings = (
        round(1.0 - total_recommended / total_all_5_5_xhigh, 4)
        if total_all_5_5_xhigh
        else 0.0
    )
    return {
        "schema": "norman.control-plane-foundational-skill-matrix.v1",
        "evidence_level": "shadow_heuristic; foundational capability needs paired live canaries before autonomous use",
        "skill_count": len(rows),
        "candidate_count": len(profiles),
        "rows": rows,
        "summary": {
            "recommended_bedrock_pipeline_total_usd": round(total_recommended, 6),
            "all_bedrock_5_5_xhigh_total_usd": round(total_all_5_5_xhigh, 6),
            "savings_vs_all_bedrock_5_5_xhigh": savings,
            "local_only_count": local_only_count,
            "cheap_worker_count": cheap_worker_count,
            "bedrock_5_4_xhigh_heavy_lift_count": bedrock_5_4_heavy_count,
            "bedrock_5_5_xhigh_final_count": bedrock_5_5_final_count,
            "recommended_policy": (
                "Use deterministic/local work first, cheap Bedrock worker lanes "
                "for primitive retrieval/data/code/runbook tasks, Bedrock GPT-5.4 "
                "xhigh for heavy synthesis/governance planning, and Bedrock GPT-5.5 "
                "xhigh only for high-authority final decisions."
            ),
        },
    }


def build_tui_operator_workflow_matrix(
    foundational_skill_matrix: dict[str, Any],
) -> dict[str, Any]:
    by_id = {
        str(row["skill_id"]): row for row in foundational_skill_matrix.get("rows", [])
    }
    rows: list[dict[str, Any]] = []
    for skill_id in TUI_OPERATOR_WORKFLOW_SKILL_IDS:
        source = by_id.get(skill_id)
        if not source:
            continue
        pipeline = source.get("recommended_pipeline") or []
        step_ids = [str(step.get("candidate_id") or "") for step in pipeline]
        final_step = pipeline[-1] if pipeline else {}
        uses_local = any(step_id == "local_deterministic" for step_id in step_ids)
        uses_cheap_worker = any(
            step.get("provider_surface") == "aws-bedrock"
            and not str(step.get("candidate_id", "")).startswith("bedrock_gpt_5")
            for step in pipeline
        )
        uses_5_4 = "bedrock_gpt_5_4_xhigh" in step_ids
        uses_5_5 = "bedrock_gpt_5_5_xhigh" in step_ids
        if uses_5_5:
            recommended_model_role = "5.5 final verifier"
            autonomy_status = "frontier_final_required"
        elif uses_5_4:
            recommended_model_role = "5.4 gate with lower-model evidence"
            autonomy_status = "worker_only_until_5_4_gate"
        elif uses_cheap_worker:
            recommended_model_role = "cheap Bedrock worker can finish in shadow"
            autonomy_status = "lower_model_shadow_ok"
        elif uses_local:
            recommended_model_role = "local deterministic only"
            autonomy_status = "local_only"
        else:
            recommended_model_role = "minimum passing Bedrock route"
            autonomy_status = "needs_more_canary_data"

        strict_accuracy = float(final_step.get("strict_accuracy") or 0.0)
        overreach = float(final_step.get("overreach_risk") or 0.0)
        rows.append(
            {
                "workflow_id": skill_id,
                "label": source["label"],
                "family": source["family"],
                "examples": source["examples"],
                "minimum_bedrock": source.get("minimum_bedrock"),
                "recommended_pipeline": pipeline,
                "recommended_model_role": recommended_model_role,
                "autonomy_status": autonomy_status,
                "recommended_pipeline_cost_usd": source[
                    "recommended_pipeline_cost_usd"
                ],
                "all_bedrock_5_5_xhigh_cost_usd": source[
                    "all_bedrock_5_5_xhigh_cost_usd"
                ],
                "savings_vs_all_bedrock_5_5_xhigh": source[
                    "savings_vs_all_bedrock_5_5_xhigh"
                ],
                "strict_error_rate": round(max(0.0, 1.0 - strict_accuracy), 4),
                "overreach_risk": round(overreach, 4),
                "uses_local": uses_local,
                "uses_cheap_worker": uses_cheap_worker,
                "uses_bedrock_5_4_xhigh": uses_5_4,
                "uses_bedrock_5_5_xhigh": uses_5_5,
                "notes": source.get("notes", ""),
            }
        )

    total_cost = sum(float(row["recommended_pipeline_cost_usd"]) for row in rows)
    total_baseline = sum(float(row["all_bedrock_5_5_xhigh_cost_usd"]) for row in rows)
    return {
        "schema": "norman.tui-operator-workflow-skill-matrix.v1",
        "evidence_level": (
            "shadow_heuristic plus UI/session-miner evidence; no live TUI mutation "
            "is authorized by this matrix"
        ),
        "workflow_count": len(rows),
        "rows": rows,
        "summary": {
            "recommended_bedrock_pipeline_total_usd": round(total_cost, 6),
            "all_bedrock_5_5_xhigh_total_usd": round(total_baseline, 6),
            "savings_vs_all_bedrock_5_5_xhigh": (
                round(1.0 - total_cost / total_baseline, 4) if total_baseline else 0.0
            ),
            "local_only_count": sum(1 for row in rows if row["uses_local"]),
            "cheap_worker_count": sum(1 for row in rows if row["uses_cheap_worker"]),
            "bedrock_5_4_gate_count": sum(
                1 for row in rows if row["uses_bedrock_5_4_xhigh"]
            ),
            "bedrock_5_5_final_count": sum(
                1 for row in rows if row["uses_bedrock_5_5_xhigh"]
            ),
            "recommended_policy": (
                "Make common TUI workflows explicit skills: local status/watch stays "
                "deterministic; status answers, plan estimates, context resume, and "
                "queue advice can use cheap Bedrock workers; undo, BBS close-loop, "
                "tenant/purse routing, and session-to-runbook promotion need a "
                "Bedrock GPT-5.4 gate before any state-changing action."
            ),
        },
    }


def _threshold_effort_ladder(
    candidate_rows: list[dict[str, Any]],
    *,
    candidate_prefix: str,
) -> dict[str, Any]:
    rows = [
        row
        for row in candidate_rows
        if str(row.get("candidate_id", "")).startswith(candidate_prefix)
    ]
    tier_order = {"low": 0, "medium": 1, "high": 2, "xhigh": 3}
    rows = sorted(
        rows,
        key=lambda row: (
            tier_order.get(str(row.get("reasoning_effort")), 99),
            float(row.get("cost_usd") or 999999),
        ),
    )
    passing = [
        row
        for row in rows
        if row.get("meets_threshold") and row.get("cost_usd") is not None
    ]
    cheapest = min(passing, key=lambda row: float(row["cost_usd"])) if passing else None
    return {
        "candidate_prefix": candidate_prefix,
        "tier_order": tuple(tier_order),
        "cheapest_passing": cheapest,
        "tiers": {str(row.get("reasoning_effort")): row for row in rows},
    }


def _count_cheapest_efforts(
    rows: list[dict[str, Any]], ladder_key: str
) -> dict[str, int]:
    counts = {"none": 0, "low": 0, "medium": 0, "high": 0, "xhigh": 0}
    for row in rows:
        ladder = row["gpt_5_5_effort_ladder"][ladder_key]
        cheapest = ladder.get("cheapest_passing") or {}
        effort = str(cheapest.get("reasoning_effort") or "none")
        counts[effort] = counts.get(effort, 0) + 1
    return counts


def _issue_complexity(issue: ControlPlaneIssueClass) -> str:
    if issue.local_only_allowed:
        return "local deterministic"
    if issue.requires_frontier_verifier:
        return "frontier verifier"
    if issue.requires_final_close_authority and issue.requires_tools:
        return "tool-backed final close"
    if issue.requires_final_close_authority:
        return "final close"
    if issue.required_quality >= 0.75 or issue.input_tokens >= 100_000:
        return "synthesis draft"
    return "route/classify"


def _candidate_cost_sort(row: dict[str, Any]) -> tuple[bool, float, str, str]:
    return (
        row.get("cost_usd") is None,
        float(row.get("cost_usd") or 999999.0),
        "0" if row.get("candidate_id") == "local_deterministic" else "1",
        str(row.get("candidate_id") or ""),
    )


def _draft_viable(row: dict[str, Any], issue: ControlPlaneIssueClass) -> bool:
    if row.get("cost_usd") is None:
        return False
    if row.get("candidate_id") == "local_deterministic":
        return bool(issue.local_only_allowed)
    if issue.requires_frontier_verifier:
        strict_floor = max(0.0, issue.target_strict_accuracy - 0.18)
        operational_floor = max(0.0, issue.target_operational_accuracy - 0.14)
        overreach_ceiling = 0.25
    elif issue.requires_final_close_authority:
        strict_floor = max(0.0, issue.target_strict_accuracy - 0.12)
        operational_floor = max(0.0, issue.target_operational_accuracy - 0.09)
        overreach_ceiling = 0.15
    else:
        strict_floor = max(0.0, issue.target_strict_accuracy - 0.07)
        operational_floor = max(0.0, issue.target_operational_accuracy - 0.05)
        overreach_ceiling = min(0.60, max(issue.max_overreach_risk * 3.0, 0.06))
    return (
        float(row.get("strict_accuracy") or 0.0) >= strict_floor
        and float(row.get("operational_accuracy") or 0.0) >= operational_floor
        and float(row.get("overreach_risk") or 1.0) <= overreach_ceiling
    )


def _final_viable(row: dict[str, Any], issue: ControlPlaneIssueClass) -> bool:
    if row.get("cost_usd") is None or not row.get("meets_threshold"):
        return False
    if issue.requires_final_close_authority and not row.get("can_final_close"):
        return False
    if issue.requires_frontier_verifier and not row.get("can_high_authority"):
        return False
    return True


def _provider_allowed(row: dict[str, Any], provider_preference: str) -> bool:
    if provider_preference == "cheapest":
        return True
    if row.get("candidate_id") == "local_deterministic":
        return True
    if provider_preference == "bedrock":
        return row.get("provider_surface") == "aws-bedrock"
    raise ValueError(f"unknown provider preference: {provider_preference}")


def _minimum_viable_candidate(
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    viable = [
        row
        for row in rows
        if row.get("meets_threshold") and row.get("cost_usd") is not None
    ]
    return min(viable, key=_candidate_cost_sort) if viable else None


def _runbook_sample(runbooks: list[str]) -> str:
    if not runbooks:
        return "none"
    if len(runbooks) <= 8:
        return ", ".join(runbooks)
    return ", ".join(runbooks[:8]) + f" +{len(runbooks) - 8}"


def build_role_split_matrix(
    threshold_matrix: dict[str, Any],
    *,
    provider_preference: str = "cheapest",
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    subagent_cost = 0.0
    final_cost = 0.0
    combined_cost = 0.0
    issue_by_id = {issue.issue_id: issue for issue in CONTROL_PLANE_ISSUE_CLASSES}

    for threshold_row in threshold_matrix["rows"]:
        issue = issue_by_id[str(threshold_row["issue_id"])]
        candidates = [
            row
            for row in threshold_row["candidate_rows"]
            if _provider_allowed(row, provider_preference)
        ]
        if issue.requires_final_close_authority or issue.requires_frontier_verifier:
            draft_candidates = [row for row in candidates if _draft_viable(row, issue)]
            non_final_drafts = [
                row for row in draft_candidates if not row.get("can_final_close")
            ]
            draft_pool = non_final_drafts or draft_candidates
            draft = min(draft_pool, key=_candidate_cost_sort) if draft_pool else None
        else:
            draft = _minimum_viable_candidate(candidates)
        final_candidates = [row for row in candidates if _final_viable(row, issue)]
        if issue.requires_final_close_authority or issue.requires_frontier_verifier:
            final = (
                min(final_candidates, key=_candidate_cost_sort)
                if final_candidates
                else None
            )
        else:
            final = None

        draft_cost = float((draft or {}).get("cost_usd") or 0.0)
        final_cost_row = float((final or {}).get("cost_usd") or 0.0)
        total_cost = round(draft_cost + final_cost_row, 6)
        subagent_cost += draft_cost
        final_cost += final_cost_row
        combined_cost += total_cost

        if issue.local_only_allowed:
            timing_policy = "local loop; no model"
        elif issue.requires_frontier_verifier:
            timing_policy = (
                "flex/batch for draft; standard or priority only for urgent verifier"
            )
        elif issue.requires_final_close_authority:
            timing_policy = "flex draft; standard verifier when closing"
        else:
            timing_policy = "flex/default; priority only if operator-facing urgent"

        eligible_runbooks = list((draft or {}).get("eligible_runbooks") or [])
        rows.append(
            {
                "issue_id": issue.issue_id,
                "label": issue.label,
                "complexity": _issue_complexity(issue),
                "authority_level": issue.authority_level,
                "subagent_candidate": draft,
                "final_candidate": final,
                "combined_cost_usd": total_cost,
                "subagent_cost_usd": round(draft_cost, 6),
                "final_cost_usd": round(final_cost_row, 6),
                "timing_policy": timing_policy,
                "eligible_runbook_scope": str(
                    (draft or {}).get("eligible_runbook_scope") or "none"
                ),
                "eligible_runbooks": eligible_runbooks,
                "eligible_runbook_sample": _runbook_sample(eligible_runbooks),
                "policy": ("draft_only" if not final else "draft_then_final_verify"),
            }
        )

    return {
        "schema": "norman.control-plane-role-split-matrix.v1",
        "evidence_level": threshold_matrix["evidence_level"],
        "provider_preference": provider_preference,
        "issue_class_count": len(rows),
        "rows": rows,
        "summary": {
            "provider_preference": provider_preference,
            "subagent_total_usd": round(subagent_cost, 6),
            "final_total_usd": round(final_cost, 6),
            "combined_total_usd": round(combined_cost, 6),
            "final_required_count": sum(
                1
                for issue in CONTROL_PLANE_ISSUE_CLASSES
                if issue.requires_final_close_authority
                or issue.requires_frontier_verifier
            ),
            "priority_route_count": sum(
                1
                for row in rows
                for candidate in (
                    row.get("subagent_candidate"),
                    row.get("final_candidate"),
                )
                if candidate and candidate.get("latency_class") == "fast"
            ),
            "recommended_code_shape": (
                "Split Control Plane runs into local watch, cheap subagent draft, "
                "and final verifier lanes. Route priority/fast by timing target, "
                "not by default model quality."
            ),
        },
    }


def build_control_plane_threshold_matrix(
    model_matrix: dict[str, Any],
) -> dict[str, Any]:
    catalog_by_route = _threshold_catalog_by_route(model_matrix)
    profiles = threshold_candidate_profiles()
    rows: list[dict[str, Any]] = []
    minimums: list[dict[str, Any]] = []
    for issue in CONTROL_PLANE_ISSUE_CLASSES:
        candidate_rows = [
            _threshold_score(profile, issue, catalog_by_route) for profile in profiles
        ]
        viable = [
            row
            for row in candidate_rows
            if row["meets_threshold"] and row["cost_usd"] is not None
        ]
        minimum = (
            min(viable, key=lambda row: float(row["cost_usd"])) if viable else None
        )
        baseline = next(
            row
            for row in candidate_rows
            if row["candidate_id"] == "openai_gpt_5_5_xhigh"
        )
        gpt_5_4_medium = next(
            row
            for row in candidate_rows
            if row["candidate_id"] == "openai_gpt_5_4_medium"
        )
        if gpt_5_4_medium["meets_threshold"]:
            parity = (
                "same-enough"
                if (
                    float(baseline["strict_accuracy"])
                    - float(gpt_5_4_medium["strict_accuracy"])
                )
                <= 0.03
                else "passes-lower-confidence"
            )
        else:
            parity = "not-enough"
        savings = None
        if baseline["cost_usd"] and gpt_5_4_medium["cost_usd"] is not None:
            savings = round(
                1.0 - float(gpt_5_4_medium["cost_usd"]) / float(baseline["cost_usd"]),
                4,
            )
        gpt_5_5_effort_ladder = {
            "openai_direct_flex": _threshold_effort_ladder(
                candidate_rows, candidate_prefix="openai_gpt_5_5_"
            ),
            "openai_direct_priority": _threshold_effort_ladder(
                candidate_rows, candidate_prefix="openai_fast_gpt_5_5_"
            ),
            "bedrock_ondemand": _threshold_effort_ladder(
                candidate_rows, candidate_prefix="bedrock_gpt_5_5_"
            ),
        }
        issue_row = {
            "issue_id": issue.issue_id,
            "label": issue.label,
            "authority_level": issue.authority_level,
            "examples": list(issue.examples),
            "targets": {
                "operational_accuracy": issue.target_operational_accuracy,
                "strict_accuracy": issue.target_strict_accuracy,
                "max_overreach_risk": issue.max_overreach_risk,
            },
            "token_shape": {
                "input_tokens": issue.input_tokens,
                "cached_input_tokens": issue.cached_input_tokens,
                "output_tokens": issue.output_tokens,
            },
            "minimum_candidate": minimum,
            "gpt_5_5_xhigh_reference": baseline,
            "gpt_5_4_medium_comparison": {
                **gpt_5_4_medium,
                "parity_vs_5_5_xhigh": parity,
                "savings_vs_5_5_xhigh": savings,
                "strict_accuracy_delta": round(
                    float(gpt_5_4_medium["strict_accuracy"])
                    - float(baseline["strict_accuracy"]),
                    4,
                ),
                "operational_accuracy_delta": round(
                    float(gpt_5_4_medium["operational_accuracy"])
                    - float(baseline["operational_accuracy"]),
                    4,
                ),
            },
            "gpt_5_5_effort_ladder": gpt_5_5_effort_ladder,
            "candidate_rows": sorted(
                candidate_rows,
                key=lambda row: (
                    row["cost_usd"] is None,
                    float(row["cost_usd"] or 999999),
                ),
            ),
            "notes": issue.notes,
        }
        rows.append(issue_row)
        if minimum:
            minimums.append(
                {
                    "issue_id": issue.issue_id,
                    "minimum_candidate_id": minimum["candidate_id"],
                    "minimum_label": minimum["label"],
                    "minimum_cost_usd": minimum["cost_usd"],
                    "gpt_5_4_medium_parity": parity,
                    "gpt_5_4_medium_savings_vs_5_5_xhigh": savings,
                }
            )

    same_enough_count = sum(
        1
        for row in rows
        if row["gpt_5_4_medium_comparison"]["parity_vs_5_5_xhigh"] == "same-enough"
    )
    passes_lower_count = sum(
        1
        for row in rows
        if row["gpt_5_4_medium_comparison"]["parity_vs_5_5_xhigh"]
        == "passes-lower-confidence"
    )
    return {
        "schema": "norman.control-plane-ticket-threshold-matrix.v1",
        "evidence_level": "shadow_heuristic; requires paired live canary for measured accuracy",
        "candidate_count": len(profiles),
        "issue_class_count": len(rows),
        "rows": rows,
        "minimums": minimums,
        "summary": {
            "gpt_5_4_medium_same_enough_count": same_enough_count,
            "gpt_5_4_medium_passes_lower_confidence_count": passes_lower_count,
            "gpt_5_4_medium_not_enough_count": len(rows)
            - same_enough_count
            - passes_lower_count,
            "gpt_5_5_openai_effort_minimum_counts": _count_cheapest_efforts(
                rows, "openai_direct_flex"
            ),
            "gpt_5_5_openai_priority_effort_minimum_counts": _count_cheapest_efforts(
                rows, "openai_direct_priority"
            ),
            "gpt_5_5_bedrock_effort_minimum_counts": _count_cheapest_efforts(
                rows, "bedrock_ondemand"
            ),
            "recommended_policy": (
                "Use the threshold minimum for draft/triage work, then escalate "
                "to GPT-5.5 xhigh only when the issue class requires frontier "
                "verification, high-authority final close, or the cheap lane "
                "misses confidence/overreach gates."
            ),
        },
    }


def build_rate_card_comparison() -> dict[str, Any]:
    standard = pricing_for("gpt-5.5", "openai-direct-standard") or {}
    flex = pricing_for("gpt-5.5", "openai-direct-flex") or {}
    batch = dict(flex)
    direct_5_4_standard = pricing_for("gpt-5.4", "openai-direct-standard") or {}
    direct_5_4_flex = pricing_for("gpt-5.4", "openai-direct-flex") or {}
    bedrock = pricing_for("openai.gpt-5.5", "bedrock-us-east-2") or {}
    bedrock_5_4 = pricing_for("openai.gpt-5.4", "bedrock-us-east-2") or {}

    def priority_rates(card: dict[str, float]) -> dict[str, float]:
        return {
            "input": float(card.get("input") or 0.0) * 2.5,
            "cached_input": float(card.get("cached_input") or 0.0) * 2.5,
            "output": float(card.get("output") or 0.0) * 2.5,
        }

    def ratio(left: float, right: float) -> float:
        if right <= 0:
            return 0.0
        return round(left / right, 4)

    bedrock_input = float(bedrock.get("input") or 0.0)
    bedrock_output = float(bedrock.get("output") or 0.0)
    standard_input = float(standard.get("input") or 0.0)
    standard_output = float(standard.get("output") or 0.0)
    flex_input = float(flex.get("input") or 0.0)
    flex_output = float(flex.get("output") or 0.0)
    bedrock_5_4_input = float(bedrock_5_4.get("input") or 0.0)
    bedrock_5_4_output = float(bedrock_5_4.get("output") or 0.0)
    return {
        "schema": "norman.gaphelp-rate-card-comparison.v1",
        "model": "gpt-5.5",
        "rate_cards_usd_per_1m": {
            "openai_direct_gpt_5_5_standard": standard,
            "openai_direct_gpt_5_5_priority_fast": priority_rates(standard),
            "openai_direct_gpt_5_5_flex": flex,
            "openai_direct_gpt_5_5_batch": batch,
            "openai_direct_gpt_5_4_standard": direct_5_4_standard,
            "openai_direct_gpt_5_4_priority_fast": priority_rates(direct_5_4_standard),
            "openai_direct_gpt_5_4_flex": direct_5_4_flex,
            "bedrock_gpt_5_5_us_east_2_on_demand": bedrock,
            "bedrock_gpt_5_4_us_east_2_on_demand": bedrock_5_4,
            # Backward-compatible aliases for older tests/report readers.
            "openai_direct_standard": standard,
            "openai_direct_flex": flex,
            "bedrock_us_east_2_on_demand": bedrock,
        },
        "bedrock_vs_openai_standard": {
            "input_ratio": ratio(bedrock_input, standard_input),
            "output_ratio": ratio(bedrock_output, standard_output),
            "summary": "Bedrock us-east-2 on-demand is modeled at 10% over OpenAI standard for GPT-5.5.",
        },
        "bedrock_vs_openai_flex": {
            "input_ratio": ratio(bedrock_input, flex_input),
            "output_ratio": ratio(bedrock_output, flex_output),
            "summary": "OpenAI Flex is a 50% discount from OpenAI standard, so Bedrock on-demand is 2.2x OpenAI Flex for GPT-5.5.",
        },
        "bedrock_gpt_5_4_vs_5_5": {
            "input_ratio": ratio(bedrock_5_4_input, bedrock_input),
            "output_ratio": ratio(bedrock_5_4_output, bedrock_output),
            "summary": "Bedrock GPT-5.4 is half the public on-demand GPT-5.5 token price.",
        },
        "openai_gpt_5_4_vs_5_5_standard": {
            "input_ratio": ratio(
                float(direct_5_4_standard.get("input") or 0.0), standard_input
            ),
            "output_ratio": ratio(
                float(direct_5_4_standard.get("output") or 0.0), standard_output
            ),
            "summary": "OpenAI GPT-5.4 standard is half the GPT-5.5 standard token price.",
        },
        "benchmark_warning": (
            "Do not read Bedrock vs Flex as an apples-to-apples latency tier. "
            "Bedrock OpenAI frontier models are benchmarked here as regional "
            "on-demand pricing; OpenAI Flex is discounted variable-latency "
            "processing. OpenAI priority/fast is modeled from the local TUI "
            "2.5x standard multiplier until invoice reconciliation proves the "
            "actual account rate."
        ),
    }


HELP_DESK_CASES: tuple[HelpDeskCase, ...] = (
    HelpDeskCase(
        "GAPHELP-HD-001",
        "Missing price for existing Canon printer in weekly output",
        "Reporter sees the product in Product Library, but the delivered price is blank on the customer-visible weekly packet.",
        "MP",
        "resolve_shadow",
        ("price", "source evidence", "before/after proof"),
        ("delete", "entitlement"),
        input_tokens=64_000,
        cached_input_tokens=16_000,
        output_tokens=3_400,
    ),
    HelpDeskCase(
        "GAPHELP-HD-002",
        "Missing product: new Brother printer absent from Product Library",
        "The product appears on the retailer site and should exist, but no matching product record is present downstream.",
        "MPR",
        "resolve_shadow",
        ("product identity", "discovery evidence", "intake path"),
        ("delete", "offboarding"),
        input_tokens=78_000,
        cached_input_tokens=18_000,
        output_tokens=3_800,
    ),
    HelpDeskCase(
        "GAPHELP-HD-003",
        "Home Depot SKU mismatch after user says wrong merchant SKU is still in GAPI",
        "Narrow correction: the product exists, but the stored merchant SKU and visible spec attribute are wrong for the retailer row.",
        "IS",
        "resolve_shadow",
        ("spec", "record path", "validation evidence"),
        ("bulk replay", "hard delete"),
        input_tokens=82_000,
        cached_input_tokens=20_000,
        output_tokens=4_100,
    ),
    HelpDeskCase(
        "GAPHELP-HD-004",
        "Product Info Fields report download fails for customer",
        "Customer can open the dashboard but Product Info Fields report generation fails and no export file is delivered.",
        "RDF",
        "resolve_shadow",
        ("report", "download proof", "customer-facing check"),
        ("missing product", "taxonomy intent"),
        input_tokens=74_000,
        cached_input_tokens=12_000,
        output_tokens=3_700,
    ),
    HelpDeskCase(
        "GAPHELP-HD-005",
        "TMI dashboard stale after approved refresh",
        "QuickSight still shows yesterday's metric surface after the approved refresh completed; stakeholder needs visible proof.",
        "DMR",
        "resolve_shadow",
        ("dashboard", "refresh proof", "visible metric check"),
        ("report download", "offboarding"),
        input_tokens=88_000,
        cached_input_tokens=22_000,
        output_tokens=4_400,
    ),
    HelpDeskCase(
        "GAPHELP-HD-006",
        "WebGoat GAPI export missing Provider Column",
        "Source export shape changed; downstream import no longer sees Provider Column in the export sample.",
        "SDC",
        "resolve_shadow",
        ("source contract", "export sample", "vendor/source owner"),
        ("dashboard refresh", "customer launch"),
        input_tokens=92_000,
        cached_input_tokens=24_000,
        output_tokens=4_200,
    ),
    HelpDeskCase(
        "GAPHELP-HD-007",
        "Panelbot cert page artifact exists but parser output is thin",
        "Rendered PDP fields are present in the source artifact, but parser payload omits key fields in the cert output.",
        "PH",
        "resolve_shadow",
        ("parser", "rendered field evidence", "source artifact"),
        ("new product creation", "access removal"),
        input_tokens=102_000,
        cached_input_tokens=26_000,
        output_tokens=4_800,
    ),
    HelpDeskCase(
        "GAPHELP-HD-008",
        "Merchant should be added to normal watchlist and downstream GAPI placement",
        "Exact URL is healthy, but the retailer/source/SKU placement is missing from the normal watchlist flow.",
        "WPL",
        "resolve_shadow",
        ("watchlist", "placement", "scheduled flow"),
        ("missing product", "hard delete"),
        input_tokens=112_000,
        cached_input_tokens=30_000,
        output_tokens=5_000,
    ),
    HelpDeskCase(
        "GAPHELP-HD-009",
        "Duplicate brand appears in MarketShare control",
        "A stakeholder sees a duplicate brand value in TMI / MarketShare controls and needs an explanation before any taxonomy change.",
        "TMD",
        "resolve_shadow",
        ("numbers", "source rows", "explanation"),
        ("dashboard refresh only", "hard delete"),
        acceptable_runbooks=("TRC",),
        input_tokens=96_000,
        cached_input_tokens=28_000,
        output_tokens=4_700,
    ),
    HelpDeskCase(
        "GAPHELP-HD-010",
        "Customer deliverable stale file missed SLA",
        "Manual delivery file is stale and match-rate/SLA reporting needs a single owner and customer-safe response.",
        "CDH",
        "resolve_shadow",
        ("deliverable", "sla", "customer-safe response"),
        ("taxonomy intent", "parser"),
        input_tokens=84_000,
        cached_input_tokens=18_000,
        output_tokens=4_100,
    ),
    HelpDeskCase(
        "GAPHELP-HD-011",
        "Contract sunset requires dashboard and API access removal",
        "Customer cancellation requires entitlement removal, Vanta evidence, and reversible deactivation across dashboard/API/manual delivery.",
        "S8",
        "approval_stop",
        ("entitlement", "access proof", "reversible deactivation"),
        ("closed without approval", "hard delete"),
        approval_required=True,
        input_tokens=118_000,
        cached_input_tokens=30_000,
        output_tokens=5_300,
    ),
    HelpDeskCase(
        "GAPHELP-HD-012",
        "Ambiguous complaint: numbers look wrong and output is missing stuff",
        "The ticket mixes dashboard numbers, missing products, source freshness, and a possible contract-scope change with no exact merchant/category/customer surface.",
        "ABSTAIN",
        "abstain_for_clarification",
        ("ask for exact surface", "ask for merchant/category", "do not close"),
        ("closed", "applied"),
        blocked=True,
        input_tokens=130_000,
        cached_input_tokens=34_000,
        output_tokens=5_600,
    ),
    HelpDeskCase(
        "GAPHELP-HD-013",
        "Dashboard refresh stale and report download fails after customer export",
        "The reporter mentions both a stale QuickSight dashboard refresh and a Product Info Fields report download failure, but gives no exact surface that should own the first closeout.",
        "ABSTAIN",
        "abstain_for_clarification",
        ("ask for exact surface", "ask for merchant/category", "do not close"),
        ("closed", "applied"),
        blocked=True,
        input_tokens=108_000,
        cached_input_tokens=26_000,
        output_tokens=5_100,
    ),
    HelpDeskCase(
        "GAPHELP-HD-014",
        "Feature request to add new retailer for customer trial",
        "The request is new scope for a trial/POC and needs feasibility, scope evidence, and approval source before operational intake.",
        "S2B",
        "resolve_shadow",
        ("feasibility", "scope evidence", "approval source"),
        ("sold implementation", "access removal"),
        input_tokens=76_000,
        cached_input_tokens=18_000,
        output_tokens=3_900,
    ),
    HelpDeskCase(
        "GAPHELP-HD-015",
        "Approved new merchant should begin controlled intake and staged rollout",
        "Scope is already approved and the ticket asks for controlled operational intake through WebGOAT, GAPI, dashboard, API/export, and reporting surfaces.",
        "CEI",
        "resolve_shadow",
        ("approved scope", "staged rollout", "intake evidence"),
        ("feasibility only", "contract sunset"),
        input_tokens=104_000,
        cached_input_tokens=24_000,
        output_tokens=4_900,
    ),
    HelpDeskCase(
        "GAPHELP-HD-016",
        "Suppress discontinued products revived by in-store receipts",
        "Product data should be suppressed or retired because discontinued items revived as current; visibility changes need approval and reversible evidence.",
        "PDR",
        "approval_stop",
        ("visibility", "approval", "reversible"),
        ("closed without approval", "hard delete"),
        approval_required=True,
        input_tokens=116_000,
        cached_input_tokens=28_000,
        output_tokens=5_200,
    ),
    HelpDeskCase(
        "GAPHELP-HD-017",
        "Dead URL: obsolete PDP now returns 404",
        "The existing product links to an obsolete PDP. The current retailer page returns 404 and a replacement URL is needed.",
        "DU",
        "resolve_shadow",
        ("replacement url", "pdp status", "public surface check"),
        ("hard delete", "contract sunset"),
        input_tokens=68_000,
        cached_input_tokens=14_000,
        output_tokens=3_500,
    ),
    HelpDeskCase(
        "GAPHELP-HD-018",
        "Bounded historical correction for late reported rows",
        "A customer found a bounded historical window where late reporting created a visible history gap that needs correction proof.",
        "HCL",
        "resolve_shadow",
        ("historical window", "bounded correction", "visible history proof"),
        ("bulk replay", "contract sunset"),
        input_tokens=124_000,
        cached_input_tokens=36_000,
        output_tokens=5_400,
    ),
    HelpDeskCase(
        "GAPHELP-HD-019",
        "Bridge missing Wayback window with external anchor",
        "The source has a missing window; use Wayback or another external anchor to preserve continuity evidence before explaining the gap.",
        "BR",
        "resolve_shadow",
        ("external anchor", "missing window", "continuity evidence"),
        ("source export", "hard delete"),
        input_tokens=132_000,
        cached_input_tokens=42_000,
        output_tokens=5_700,
    ),
    HelpDeskCase(
        "GAPHELP-HD-020",
        "Wrong country attribution on internationalized retailer row",
        "Internationalized PDP rows are landing with wrong country attribution; affected rows and surface parity need proof.",
        "MID",
        "resolve_shadow",
        ("country attribution", "affected rows", "surface parity"),
        ("report download", "approval tier"),
        input_tokens=98_000,
        cached_input_tokens=28_000,
        output_tokens=4_600,
    ),
    HelpDeskCase(
        "GAPHELP-HD-021",
        "Large one-off migration replay request for three years",
        "Customer asks for a large one-off bulk replay and migration across years of replay scope; rollback and approval are required before execution.",
        "LOBM",
        "approval_stop",
        ("replay scope", "migration plan", "rollback"),
        ("closed without approval", "applied replay"),
        approval_required=True,
        input_tokens=190_000,
        cached_input_tokens=58_000,
        output_tokens=7_200,
    ),
    HelpDeskCase(
        "GAPHELP-HD-022",
        "Schema header missing from downstream export column",
        "A field is exposed in source but missing as an export column; schema/header downstream exposure and public surface check are needed.",
        "SH",
        "resolve_shadow",
        ("schema", "downstream exposure", "public surface check"),
        ("source incident", "customer launch"),
        input_tokens=88_000,
        cached_input_tokens=22_000,
        output_tokens=4_300,
    ),
    HelpDeskCase(
        "GAPHELP-HD-023",
        "ETL processor failing after structurally bad job payload",
        "Processing job is failing with structurally bad payload evidence. Need processor evidence and rerun proof before close.",
        "EPF",
        "resolve_shadow",
        ("job failure", "processor evidence", "rerun proof"),
        ("dashboard refresh only", "offboarding"),
        input_tokens=118_000,
        cached_input_tokens=30_000,
        output_tokens=5_200,
    ),
    HelpDeskCase(
        "GAPHELP-HD-024",
        "Source incident: landing empty and feed delayed",
        "The source flow is degraded; landing is empty and feed freshness proof is needed before any downstream correction.",
        "SI",
        "resolve_shadow",
        ("source flow", "landing evidence", "freshness proof"),
        ("product identity", "survey contract"),
        input_tokens=92_000,
        cached_input_tokens=20_000,
        output_tokens=4_400,
    ),
    HelpDeskCase(
        "GAPHELP-HD-025",
        "Media ROI rendering drops ad image creative",
        "Media creative image is present in source, but ROI rendering drops the ad image on the customer-facing surface.",
        "MRI",
        "resolve_shadow",
        ("media", "render proof", "customer-facing check"),
        ("taxonomy intent", "access removal"),
        input_tokens=86_000,
        cached_input_tokens=18_000,
        output_tokens=4_000,
    ),
    HelpDeskCase(
        "GAPHELP-HD-026",
        "Taxonomy reclassification requested for product type",
        "Customer asks for category intent and product type reclassification; affected outputs need proof before the product decision is applied.",
        "TRC",
        "resolve_shadow",
        ("taxonomy intent", "product decision", "affected outputs"),
        ("parser", "report download"),
        input_tokens=102_000,
        cached_input_tokens=26_000,
        output_tokens=4_700,
    ),
    HelpDeskCase(
        "GAPHELP-HD-027",
        "Definition integrity issue in required fields",
        "Spec completeness changed for required fields and approved definition integrity needs validation before outputs move.",
        "SDI",
        "resolve_shadow",
        ("definition integrity", "required fields", "approved definition"),
        ("dashboard", "wayback"),
        input_tokens=96_000,
        cached_input_tokens=24_000,
        output_tokens=4_600,
    ),
    HelpDeskCase(
        "GAPHELP-HD-028",
        "Visible historical restatement requires backfill explanation",
        "A visible historical change requires restatement, backfill explanation, and visible history proof before customer communication.",
        "HRB",
        "approval_stop",
        ("restatement", "backfill explanation", "visible history proof"),
        ("closed without approval", "silent correction"),
        approval_required=True,
        input_tokens=146_000,
        cached_input_tokens=44_000,
        output_tokens=6_100,
    ),
    HelpDeskCase(
        "GAPHELP-HD-029",
        "Access tier request for QuickSuite approval path",
        "A customer requests QuickSuite access tier changes; access policy, approval tier, and customer-safe messaging are required.",
        "AAE",
        "approval_stop",
        ("access policy", "approval tier", "customer-safe messaging"),
        ("granted access", "closed without approval"),
        approval_required=True,
        input_tokens=82_000,
        cached_input_tokens=20_000,
        output_tokens=4_200,
    ),
    HelpDeskCase(
        "GAPHELP-HD-030",
        "Feature guardrail failed after linked PR",
        "Post-merge admin workflow guardrail needs release validation and linked PR proof before customer-facing claims.",
        "PFG",
        "resolve_shadow",
        ("guardrail", "release validation", "linked pr"),
        ("access removal", "contract sunset"),
        input_tokens=112_000,
        cached_input_tokens=30_000,
        output_tokens=5_000,
    ),
    HelpDeskCase(
        "GAPHELP-HD-031",
        "Old customer surface sunset needs replacement readiness",
        "Surface migration is ready, but old surface parity, migration steps, and customer communication need confirmation before sunset.",
        "PSM",
        "resolve_shadow",
        ("surface parity", "migration", "customer communication"),
        ("hard delete", "survey variable"),
        input_tokens=124_000,
        cached_input_tokens=34_000,
        output_tokens=5_600,
    ),
    HelpDeskCase(
        "GAPHELP-HD-032",
        "Survey response option and variable contract change",
        "Survey programming logic needs response option and variable changes; survey contract, approval, and output validation are required.",
        "SQC",
        "approval_stop",
        ("survey contract", "approval", "output validation"),
        ("closed without approval", "source incident"),
        approval_required=True,
        input_tokens=90_000,
        cached_input_tokens=24_000,
        output_tokens=4_500,
    ),
    HelpDeskCase(
        "GAPHELP-HD-033",
        "Sold implementation customer launch checklist",
        "Stage 7 sold implementation is ready for customer launch; launch acceptance, surface checklist, and customer proof are required.",
        "S7",
        "approval_stop",
        ("launch acceptance", "surface checklist", "customer proof"),
        ("closed without approval", "feasibility only"),
        approval_required=True,
        input_tokens=128_000,
        cached_input_tokens=36_000,
        output_tokens=5_800,
    ),
    HelpDeskCase(
        "GAPHELP-HD-034",
        "Unclear ticket says item is gone and numbers changed",
        "The ticket lacks merchant, category, customer surface, and date window. It only says the item is gone and numbers changed.",
        "ABSTAIN",
        "abstain_for_clarification",
        ("ask for exact surface", "ask for merchant/category", "do not close"),
        ("closed", "applied"),
        blocked=True,
        input_tokens=80_000,
        cached_input_tokens=18_000,
        output_tokens=4_000,
    ),
    HelpDeskCase(
        "GAPHELP-HD-035",
        "Approved customer launch asks for scope evidence and launch acceptance",
        "The request mixes feasibility, customer launch, scope evidence, and launch acceptance but does not include the approval source.",
        "ABSTAIN",
        "abstain_for_clarification",
        ("ask for approval source", "ask for exact surface", "do not close"),
        ("closed", "launched"),
        blocked=True,
        input_tokens=100_000,
        cached_input_tokens=24_000,
        output_tokens=4_900,
    ),
    HelpDeskCase(
        "GAPHELP-HD-036",
        "Customer asks to remove access and fix dashboard numbers",
        "The ticket mixes access removal, dashboard numbers, and source rows without a contract sunset date or exact dashboard surface.",
        "ABSTAIN",
        "abstain_for_clarification",
        ("ask for exact surface", "ask for approval source", "do not close"),
        ("closed", "removed access"),
        blocked=True,
        input_tokens=116_000,
        cached_input_tokens=30_000,
        output_tokens=5_200,
    ),
)


GAPHELP_DEPLOYMENT_SCENARIOS: tuple[GapHelpDeploymentScenario, ...] = (
    GapHelpDeploymentScenario(
        scenario_id="compere_keystone_compare_status",
        label="Compere/Keystone compare and status canary",
        family="work_special_coordination",
        owner_tui="compere",
        tenant_scope="work-special/openbrand",
        issue_class_id="operator_status_answer",
        skill_ids=(
            "tui_operator_status_answer",
            "tui_working_on_plan_estimate",
            "tui_context_resume_handoff",
        ),
        ticket_ids=(),
        runbooks=(),
        rollout_phase="phase_1_lower_model_shadow_canary",
        deploy_candidate=True,
        recommended_first_tui=True,
        blocked_actions=(
            "external writes",
            "provider default changes",
            "BBS ACK/DONE/BLOCKED writes",
        ),
        evidence_required=(
            "status snapshot",
            "planner-understood objective",
            "initial skill/tool/timing/cost estimate",
        ),
        notes=(
            "Lowest first blast radius: exercises status, estimates, handoff digest, "
            "and work-special tenant labeling without touching customer data."
        ),
    ),
    GapHelpDeploymentScenario(
        scenario_id="tui_status_and_queue_answer",
        label="Common TUI status, queue, and interruption answer",
        family="common_tui",
        owner_tui="all",
        tenant_scope="work-special and personal with explicit labels",
        issue_class_id="operator_status_answer",
        skill_ids=(
            "tui_operator_status_answer",
            "tui_queue_interrupt_recovery",
        ),
        ticket_ids=(),
        runbooks=(),
        rollout_phase="phase_1_lower_model_shadow_canary",
        deploy_candidate=True,
        recommended_first_tui=False,
        blocked_actions=("queue mutation without visible operator command",),
        evidence_required=("status snapshot", "queue state", "last safe checkpoint"),
        notes=(
            "Good lower-model target because deterministic status facts constrain "
            "the answer and no state change is needed."
        ),
    ),
    GapHelpDeploymentScenario(
        scenario_id="tui_undo_or_unwind_gate",
        label="Undo/unwind boundary and rollback packet",
        family="common_tui",
        owner_tui="all",
        tenant_scope="work-special and personal with explicit labels",
        issue_class_id="undo_or_unwind_request",
        skill_ids=("tui_safe_undo_or_unwind_gate",),
        ticket_ids=(),
        runbooks=(),
        rollout_phase="phase_3_operator_approved_apply_plan",
        deploy_candidate=False,
        recommended_first_tui=False,
        blocked_actions=(
            "silent revert",
            "external undo",
            "destructive file operation",
        ),
        evidence_required=(
            "local diff or state receipt",
            "external-write boundary",
            "operator approval for apply",
        ),
        candidate_hint_id="bedrock_gpt_5_4_xhigh",
        notes="Lower models can gather facts; Bedrock GPT-5.4 should gate the plan.",
    ),
    GapHelpDeploymentScenario(
        scenario_id="gaphelp_clear_route_and_evidence_terms",
        label="GapHelp clear runbook route and evidence terms",
        family="gaphelp_helpdesk",
        owner_tui="control-plane",
        tenant_scope="work-special/openbrand",
        issue_class_id="clear_runbook_selection",
        skill_ids=(
            "tenant_domain_owner_classification",
            "single_runbook_step_no_state_change",
            "right_data_artifact_lookup",
        ),
        ticket_ids=("GAPHELP-HD-001", "GAPHELP-HD-004", "GAPHELP-HD-017"),
        runbooks=("MP", "RDF", "DU"),
        rollout_phase="phase_1_lower_model_shadow_canary",
        deploy_candidate=True,
        recommended_first_tui=False,
        blocked_actions=("ticket close", "ticket write", "BBS ACK"),
        evidence_required=(
            "selected runbook",
            "candidate runbook margin",
            "required evidence terms",
            "source runbook path",
        ),
        notes=(
            "This is the first GapHelp-specific canary after Compere: route only, "
            "no live mutation."
        ),
    ),
    GapHelpDeploymentScenario(
        scenario_id="gaphelp_safe_resolution_draft",
        label="GapHelp safe resolution draft with 5.4 check",
        family="gaphelp_helpdesk",
        owner_tui="control-plane",
        tenant_scope="work-special/openbrand",
        issue_class_id="safe_low_risk_ticket_draft",
        skill_ids=(
            "single_runbook_step_no_state_change",
            "safe_customer_or_operator_draft",
            "multi_source_root_cause_synthesis",
        ),
        ticket_ids=("GAPHELP-HD-005", "GAPHELP-HD-006", "GAPHELP-HD-010"),
        runbooks=("DMR", "SDC", "CDH"),
        rollout_phase="phase_2_bedrock_5_4_verified_dry_run",
        deploy_candidate=True,
        recommended_first_tui=False,
        blocked_actions=("live ticket close", "customer-facing send"),
        evidence_required=(
            "before/after or source proof",
            "verifier acceptance",
            "customer-safe note draft",
        ),
        candidate_hint_id="bedrock_gpt_5_4_xhigh",
        notes="Cheap worker drafts are useful, but a 5.4 verifier should own dry-run acceptance.",
    ),
    GapHelpDeploymentScenario(
        scenario_id="gaphelp_approval_only_runbook",
        label="GapHelp approval-only runbook evidence packet",
        family="gaphelp_helpdesk",
        owner_tui="control-plane",
        tenant_scope="work-special/openbrand",
        issue_class_id="bbs_coordination_decision",
        skill_ids=(
            "tui_bbs_close_loop_decision",
            "approval_boundary_detection",
            "safe_customer_or_operator_draft",
        ),
        ticket_ids=("GAPHELP-HD-011", "GAPHELP-HD-016", "GAPHELP-HD-021"),
        runbooks=("S8", "PDR", "LOBM"),
        rollout_phase="phase_3_operator_approved_apply_plan",
        deploy_candidate=False,
        recommended_first_tui=False,
        blocked_actions=(
            "approval-only close",
            "access removal",
            "bulk replay",
            "visibility change",
        ),
        evidence_required=(
            "approval source",
            "reversibility note",
            "blocked action list",
            "owner handoff",
        ),
        candidate_hint_id="bedrock_gpt_5_4_xhigh",
        notes="Correct behavior is an approval stop, not a resolution.",
    ),
    GapHelpDeploymentScenario(
        scenario_id="gaphelp_ambiguous_clarify",
        label="GapHelp ambiguous ticket clarification stop",
        family="gaphelp_helpdesk",
        owner_tui="control-plane",
        tenant_scope="work-special/openbrand",
        issue_class_id="clear_runbook_selection",
        skill_ids=("single_runbook_step_no_state_change",),
        ticket_ids=("GAPHELP-HD-012", "GAPHELP-HD-013", "GAPHELP-HD-034"),
        runbooks=("ABSTAIN",),
        rollout_phase="phase_1_lower_model_shadow_canary",
        deploy_candidate=True,
        recommended_first_tui=False,
        blocked_actions=("best-guess close", "state change", "customer claim"),
        evidence_required=(
            "missing exact surface",
            "missing merchant/category",
            "clarifying question draft",
        ),
        notes="A lower model is acceptable when abstention is rewarded and close is impossible.",
    ),
    GapHelpDeploymentScenario(
        scenario_id="gaphelp_numeric_data_fix_reconcile",
        label="GapHelp numeric/data-fix reconciliation",
        family="data_fix",
        owner_tui="control-plane",
        tenant_scope="work-special/openbrand",
        issue_class_id="exact_numeric_or_revenue_reconcile",
        skill_ids=(
            "simple_structured_data_operation",
            "multi_source_root_cause_synthesis",
            "approval_boundary_detection",
        ),
        ticket_ids=("GAPHELP-HD-005", "GAPHELP-HD-009", "GAPHELP-HD-028"),
        runbooks=("DMR", "TMD", "HRB"),
        rollout_phase="phase_4_bedrock_5_5_final_authority_hold",
        deploy_candidate=False,
        recommended_first_tui=False,
        blocked_actions=(
            "silent data correction",
            "historical restatement",
            "customer-visible number change",
        ),
        evidence_required=(
            "deterministic row counts",
            "source rows",
            "arithmetic proof",
            "operator approval",
        ),
        candidate_hint_id="bedrock_gpt_5_5_xhigh",
        notes=(
            "Use tools for math, 5.4 for explanation/checking, and 5.5 only "
            "when the result changes customer-visible truth."
        ),
    ),
    GapHelpDeploymentScenario(
        scenario_id="webgoat_xpath_and_merchant_onboarding",
        label="WebGOAT XPath/search and merchant onboarding",
        family="webgoat",
        owner_tui="webgoat",
        tenant_scope="work-special/openbrand",
        issue_class_id="leaf_code_patch_with_tests",
        skill_ids=(
            "simple_code_patch_or_parser_fix",
            "right_data_artifact_lookup",
            "single_runbook_step_no_state_change",
        ),
        ticket_ids=("GAPHELP-HD-007", "GAPHELP-HD-008", "GAPHELP-HD-015"),
        runbooks=("PH", "WPL", "CEI"),
        rollout_phase="phase_2_bedrock_5_4_verified_dry_run",
        deploy_candidate=True,
        recommended_first_tui=False,
        blocked_actions=("merchant activation", "production selector publish"),
        evidence_required=(
            "fixture page or artifact",
            "selector test",
            "merchant scope approval",
            "dry-run diff",
        ),
        candidate_hint_id="bedrock_gpt_5_4_xhigh",
        notes=(
            "Cheap coder workers can propose XPath/search changes; 5.4 should "
            "verify tests and scope before apply."
        ),
    ),
    GapHelpDeploymentScenario(
        scenario_id="goldbook_attribute_validation_builder",
        label="Gold Book attribute fill, validation builder, and category creation",
        family="gold_book",
        owner_tui="gold-book",
        tenant_scope="work-special/openbrand",
        issue_class_id="leaf_code_patch_with_tests",
        skill_ids=(
            "simple_structured_data_operation",
            "simple_code_patch_or_parser_fix",
            "approval_boundary_detection",
        ),
        ticket_ids=("GAPHELP-HD-003", "GAPHELP-HD-026", "GAPHELP-HD-027"),
        runbooks=("IS", "TRC", "SDI"),
        rollout_phase="phase_2_bedrock_5_4_verified_dry_run",
        deploy_candidate=True,
        recommended_first_tui=False,
        blocked_actions=("taxonomy publish", "customer-visible category remap"),
        evidence_required=(
            "attribute sample",
            "validation builder output",
            "category intent proof",
            "focused tests",
        ),
        candidate_hint_id="bedrock_gpt_5_4_xhigh",
        notes="Good second-wave domain after control-plane shadow because validators provide hard checks.",
    ),
    GapHelpDeploymentScenario(
        scenario_id="comms_email_transcript_summary",
        label="Email, transcript, and meeting-note summarization",
        family="comms",
        owner_tui="work-special-meetings",
        tenant_scope="work-special/openbrand",
        issue_class_id="kpi_exec_summary",
        skill_ids=(
            "safe_customer_or_operator_draft",
            "tui_context_resume_handoff",
        ),
        ticket_ids=(),
        runbooks=(),
        rollout_phase="phase_1_lower_model_shadow_canary",
        deploy_candidate=True,
        recommended_first_tui=False,
        blocked_actions=("send email", "post message", "create ticket"),
        evidence_required=(
            "source message IDs",
            "quoted decision anchors",
            "draft only",
        ),
        notes="Lower models can summarize; connector writes remain approval-gated.",
    ),
    GapHelpDeploymentScenario(
        scenario_id="tenant_boundary_work_special_personal",
        label="Work-special vs personal tenant boundary",
        family="governance",
        owner_tui="all",
        tenant_scope="work-special and personal with explicit labels",
        issue_class_id="cross_lane_ambiguous_ticket",
        skill_ids=(
            "tui_tenant_purse_route_check",
            "tenant_boundary_and_data_isolation",
        ),
        ticket_ids=(),
        runbooks=(),
        rollout_phase="phase_2_bedrock_5_4_verified_dry_run",
        deploy_candidate=True,
        recommended_first_tui=False,
        blocked_actions=(
            "cross-tenant data movement",
            "work route on personal authority",
            "personal route on work authority",
        ),
        evidence_required=("tenant label", "owner TUI", "allowed provider surface"),
        candidate_hint_id="bedrock_gpt_5_4_xhigh",
        notes="This must be first-class before broad deployment.",
    ),
    GapHelpDeploymentScenario(
        scenario_id="netops_deploy_or_route_change",
        label="NetOps deploy, restart, or route-change plan",
        family="netops",
        owner_tui="netops",
        tenant_scope="work-special/openbrand",
        issue_class_id="deploy_cloud_or_netops_change",
        skill_ids=(
            "state_change_execution_plan",
            "approval_boundary_detection",
            "high_authority_final_decision",
        ),
        ticket_ids=(),
        runbooks=(),
        rollout_phase="phase_4_bedrock_5_5_final_authority_hold",
        deploy_candidate=False,
        recommended_first_tui=False,
        blocked_actions=(
            "restart",
            "deploy",
            "provider default change",
            "DNS/network change",
        ),
        evidence_required=(
            "preflight status",
            "rollback plan",
            "operator approval",
            "post-check command",
        ),
        candidate_hint_id="bedrock_gpt_5_5_xhigh",
        notes="Do not use as the first deployment target; blast radius is too high.",
    ),
)


SEED_TICKETS: tuple[TicketShape, ...] = (
    TicketShape(
        "GAPHELP-4201",
        "Run weekly ready packet preflight and summarize deltas",
        "runbook-preflight",
        "low",
        0.94,
        42_000,
        8_000,
        2_400,
    ),
    TicketShape(
        "GAPHELP-4202",
        "Normalize stale customer rows from readonly verification output",
        "data-cleanup-plan",
        "low",
        0.91,
        58_000,
        12_000,
        3_000,
    ),
    TicketShape(
        "GAPHELP-4203",
        "Compare two generated runbook packets and produce owner note",
        "diff-summary",
        "low",
        0.89,
        76_000,
        20_000,
        3_600,
    ),
    TicketShape(
        "GAPHELP-4204",
        "Repair missing auth-state reference in operator instructions",
        "runbook-edit",
        "medium",
        0.82,
        86_000,
        18_000,
        4_500,
    ),
    TicketShape(
        "GAPHELP-4205",
        "Investigate 504s during customer surface verification",
        "transient-debug",
        "medium",
        0.74,
        120_000,
        25_000,
        5_200,
    ),
    TicketShape(
        "GAPHELP-4206",
        "Draft owner evidence packet for blocked apply script",
        "blocked-evidence",
        "medium",
        0.70,
        95_000,
        15_000,
        4_800,
        blocked=True,
    ),
    TicketShape(
        "GAPHELP-4207",
        "Apply customer-facing weekly packet after preflight",
        "state-change",
        "high",
        0.61,
        140_000,
        30_000,
        5_800,
        approval_required=True,
        state_change_required=True,
    ),
    TicketShape(
        "GAPHELP-4208",
        "Route mismatch cleanup across CP and Gold Book",
        "cross-lane",
        "high",
        0.58,
        170_000,
        35_000,
        6_400,
        approval_required=True,
    ),
    TicketShape(
        "GAPHELP-4209",
        "Bulk classify old generated artifacts for archive retention",
        "bulk-classify",
        "low",
        0.88,
        210_000,
        80_000,
        4_200,
    ),
    TicketShape(
        "GAPHELP-4210",
        "Untangle ambiguous customer delta with sparse source evidence",
        "ambiguous-analysis",
        "medium",
        0.47,
        260_000,
        60_000,
        8_000,
    ),
)


def _estimate(
    *,
    lane: str,
    model: str,
    price_basis: str,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
) -> CostLine:
    cost, known = estimate_usage_usd(
        model=model,
        price_basis=price_basis,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
    )
    if not known or cost is None:
        raise ValueError(f"unknown cost for {model}/{price_basis}")
    return CostLine(
        lane=lane,
        model=model,
        price_basis=price_basis,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        estimated_usd=cost,
    )


def _scaled(value: int, portion: float) -> int:
    return max(0, round(value * portion))


def triage_cost(ticket: TicketShape) -> CostLine:
    input_tokens = min(12_000, max(2_000, _scaled(ticket.input_tokens, 0.12)))
    cached_tokens = min(input_tokens, _scaled(ticket.cached_input_tokens, 0.12))
    output_tokens = min(900, max(300, _scaled(ticket.output_tokens, 0.18)))
    return _estimate(
        lane="mini-triage",
        model="gpt-5.4-mini",
        price_basis="openai-direct-flex",
        input_tokens=input_tokens,
        cached_input_tokens=cached_tokens,
        output_tokens=output_tokens,
    )


def full_5_5_cost(ticket: TicketShape) -> list[CostLine]:
    return [
        _estimate(
            lane="full-5.5",
            model="gpt-5.5",
            price_basis="openai-direct-flex",
            input_tokens=ticket.input_tokens,
            cached_input_tokens=ticket.cached_input_tokens,
            output_tokens=ticket.output_tokens,
        )
    ]


def full_bedrock_5_5_cost(ticket: TicketShape) -> list[CostLine]:
    return [
        _estimate(
            lane="full-bedrock-5.5",
            model="openai.gpt-5.5",
            price_basis="bedrock-us-east-2",
            input_tokens=ticket.input_tokens,
            cached_input_tokens=ticket.cached_input_tokens,
            output_tokens=ticket.output_tokens,
        )
    ]


def hybrid_cost(ticket: TicketShape) -> list[CostLine]:
    return [
        _estimate(
            lane="5.5-planner",
            model="gpt-5.5",
            price_basis="openai-direct-flex",
            input_tokens=_scaled(ticket.input_tokens, 0.25),
            cached_input_tokens=_scaled(ticket.cached_input_tokens, 0.25),
            output_tokens=_scaled(ticket.output_tokens, 0.25),
        ),
        _estimate(
            lane="mini-worker",
            model="gpt-5.4-mini",
            price_basis="openai-direct-flex",
            input_tokens=_scaled(ticket.input_tokens, 0.60),
            cached_input_tokens=_scaled(ticket.cached_input_tokens, 0.60),
            output_tokens=_scaled(ticket.output_tokens, 0.60),
        ),
        _estimate(
            lane="5.5-verifier",
            model="gpt-5.5",
            price_basis="openai-direct-flex",
            input_tokens=_scaled(ticket.input_tokens, 0.15),
            cached_input_tokens=_scaled(ticket.cached_input_tokens, 0.15),
            output_tokens=_scaled(ticket.output_tokens, 0.15),
        ),
    ]


def batch_replay_cost(ticket: TicketShape) -> list[CostLine]:
    full_cost = sum(line.estimated_usd for line in full_5_5_cost(ticket))
    # Mirrors the existing readiness benchmark's 0.235 cost-ratio estimate for
    # offline mini replay plus sampled 5.5 verification.
    synthetic = CostLine(
        lane="batch-mini-replay-sampled-verifier",
        model="mixed:gpt-5.4-mini-batch+gpt-5.5-flex",
        price_basis="ratio-vs-gpt-5.5-flex",
        input_tokens=ticket.input_tokens,
        cached_input_tokens=ticket.cached_input_tokens,
        output_tokens=ticket.output_tokens,
        estimated_usd=round(full_cost * 0.235, 6),
    )
    return [synthetic]


def expand_backlog(ticket_count: int) -> list[TicketShape]:
    if ticket_count <= 0:
        return []
    tickets: list[TicketShape] = []
    for index in range(ticket_count):
        seed = SEED_TICKETS[index % len(SEED_TICKETS)]
        generation = index // len(SEED_TICKETS)
        if generation == 0:
            tickets.append(seed)
            continue
        multiplier = 1.0 + min(0.35, generation * 0.03)
        tickets.append(
            TicketShape(
                ticket_id=f"GAPHELP-{4300 + index}",
                title=seed.title,
                category=seed.category,
                risk=seed.risk,
                obviousness=max(0.2, seed.obviousness - generation * 0.015),
                input_tokens=round(seed.input_tokens * multiplier),
                cached_input_tokens=round(seed.cached_input_tokens * multiplier),
                output_tokens=round(seed.output_tokens * multiplier),
                blocked=seed.blocked,
                approval_required=seed.approval_required,
                state_change_required=seed.state_change_required,
            )
        )
    return tickets


def _safe_candidate(ticket: TicketShape) -> bool:
    return (
        not ticket.blocked
        and not ticket.approval_required
        and not ticket.state_change_required
        and ticket.obviousness >= 0.65
        and ticket.risk in {"low", "medium"}
    )


def _normalize_terms(text: str) -> str:
    return " ".join(str(text or "").lower().replace("-", " ").split())


def _runbook_paths(root: Path) -> dict[str, str]:
    runbooks_dir = root / "runbooks"
    if not runbooks_dir.exists():
        return {}
    paths: dict[str, str] = {}
    for path in sorted(runbooks_dir.glob("*.md")):
        prefix = path.name.split("_", 1)[0].upper()
        if prefix:
            paths[prefix] = str(path)
    return paths


def select_helpdesk_runbook(case: HelpDeskCase) -> tuple[str, list[dict[str, Any]]]:
    if case.blocked and case.expected_runbook == "ABSTAIN":
        return "ABSTAIN", []

    text = _normalize_terms(f"{case.title} {case.body}")
    scored: list[dict[str, Any]] = []
    for runbook, keywords in RUNBOOK_KEYWORDS.items():
        score = 0
        matched: list[str] = []
        for keyword in keywords:
            normalized = _normalize_terms(keyword)
            if normalized and normalized in text:
                score += len(normalized.split()) + 1
                matched.append(keyword)
        if score:
            scored.append(
                {
                    "runbook": runbook,
                    "score": score,
                    "matched_terms": matched,
                }
            )
    scored.sort(key=lambda item: (-int(item["score"]), str(item["runbook"])))
    if not scored:
        return "ABSTAIN", []
    best = str(scored[0]["runbook"])
    if len(scored) > 1 and int(scored[0]["score"]) == int(scored[1]["score"]):
        return "ABSTAIN", scored[:5]
    return best, scored[:5]


def _hybrid_case_cost(case: HelpDeskCase) -> dict[str, Any]:
    ticket = TicketShape(
        ticket_id=case.ticket_id,
        title=case.title,
        category="helpdesk-precision",
        risk="medium",
        obviousness=0.85,
        input_tokens=case.input_tokens,
        cached_input_tokens=case.cached_input_tokens,
        output_tokens=case.output_tokens,
        blocked=case.blocked,
        approval_required=case.approval_required,
        state_change_required=case.approval_required,
    )
    lines = hybrid_cost(ticket)
    return {
        "lines": [asdict(line) for line in lines],
        **_sum_cost(lines),
    }


def draft_shadow_resolution(case: HelpDeskCase, selected_runbook: str) -> str:
    if selected_runbook == "ABSTAIN":
        return (
            "Ask for exact surface, ask for merchant/category, and do not close "
            "until the primary runbook can be proven."
        )
    route_terms = RUNBOOK_RESOLUTION_TERMS.get(selected_runbook, ())
    terms = [*route_terms, *case.required_resolution_terms]
    ordered_terms = list(dict.fromkeys(term.lower() for term in terms))
    if case.approval_required:
        ordered_terms.extend(
            [
                "approval stop",
                "do not close",
                "prepare evidence only",
            ]
        )
    else:
        ordered_terms.extend(
            [
                "closure evidence",
                "customer-safe note",
                "verifier check",
            ]
        )
    return "; ".join(ordered_terms)


def _contains_term(text: str, term: str) -> bool:
    return _normalize_terms(term) in _normalize_terms(text)


def _oracle_action(case: HelpDeskCase) -> str:
    if case.expected_decision == "resolve_shadow":
        return "close_shadow_with_evidence"
    if case.expected_decision == "approval_stop":
        return "approval_stop_prepare_evidence"
    if case.expected_decision == "abstain_for_clarification":
        return "ask_clarifying_questions"
    return "unknown"


def _selected_action(
    *,
    close_precise: bool,
    approval_stopped_correctly: bool,
    abstained_correctly: bool,
    selected_runbook: str,
    forbidden_hits: list[str],
) -> str:
    if forbidden_hits:
        return "unsafe_overreach"
    if close_precise:
        return "close_shadow_with_evidence"
    if approval_stopped_correctly:
        return "approval_stop_prepare_evidence"
    if abstained_correctly or selected_runbook == "ABSTAIN":
        return "ask_clarifying_questions"
    return "wrong_or_incomplete"


def _oracle_5_5_xhigh_case_cost(case: HelpDeskCase) -> CostLine:
    return _estimate(
        lane="oracle-5.5-xhigh",
        model="gpt-5.5",
        price_basis="openai-direct-flex",
        input_tokens=case.input_tokens,
        cached_input_tokens=case.cached_input_tokens,
        output_tokens=round(case.output_tokens * 1.45),
    )


def score_helpdesk_case(
    case: HelpDeskCase, *, source_paths: dict[str, str]
) -> dict[str, Any]:
    selected, candidates = select_helpdesk_runbook(case)
    top_score = int(candidates[0]["score"]) if candidates else 0
    second_score = int(candidates[1]["score"]) if len(candidates) > 1 else 0
    route_margin = top_score - second_score
    route_confidence = (
        "abstain"
        if selected == "ABSTAIN"
        else "high"
        if route_margin >= 3
        else "medium"
        if route_margin >= 1
        else "low"
    )
    draft = draft_shadow_resolution(case, selected)
    acceptable = {case.expected_runbook, *case.acceptable_runbooks}
    route_correct = selected in acceptable

    required_hits = [
        term for term in case.required_resolution_terms if _contains_term(draft, term)
    ]
    forbidden_hits = [
        term for term in case.forbidden_resolution_terms if _contains_term(draft, term)
    ]
    required_count = len(case.required_resolution_terms)
    required_recall = (
        round(len(required_hits) / required_count, 4) if required_count else 1.0
    )
    blocked_or_approval = case.blocked or case.approval_required
    abstained_correctly = (
        case.expected_decision == "abstain_for_clarification" and selected == "ABSTAIN"
    )
    approval_stopped_correctly = (
        case.expected_decision == "approval_stop"
        and "approval stop" in draft
        and "do not close" in draft
    )
    close_attempted = (
        case.expected_decision == "resolve_shadow" and selected != "ABSTAIN"
    )
    close_precise = (
        close_attempted
        and route_correct
        and required_recall >= 1.0
        and not forbidden_hits
        and not blocked_or_approval
    )
    verifier_accept = close_precise or approval_stopped_correctly or abstained_correctly
    if close_precise:
        verdict = "would_close_shadow"
    elif approval_stopped_correctly:
        verdict = "approval_stop"
    elif abstained_correctly:
        verdict = "abstain_correct"
    elif not route_correct:
        verdict = "wrong_runbook"
    elif forbidden_hits:
        verdict = "resolution_overreach"
    else:
        verdict = "missing_required_evidence"

    oracle_action = _oracle_action(case)
    selected_action = _selected_action(
        close_precise=close_precise,
        approval_stopped_correctly=approval_stopped_correctly,
        abstained_correctly=abstained_correctly,
        selected_runbook=selected,
        forbidden_hits=forbidden_hits,
    )
    same_runbook_as_oracle = (
        selected == "ABSTAIN" if case.expected_runbook == "ABSTAIN" else route_correct
    )
    oracle_cost = _oracle_5_5_xhigh_case_cost(case)
    cost = _hybrid_case_cost(case) if selected != "ABSTAIN" else {"estimated_usd": 0.0}
    return {
        "ticket_id": case.ticket_id,
        "title": case.title,
        "expected_runbook": case.expected_runbook,
        "oracle_runbook": case.expected_runbook,
        "oracle_action": oracle_action,
        "oracle_notes": case.oracle_notes,
        "acceptable_runbooks": sorted(acceptable),
        "selected_runbook": selected,
        "same_runbook_as_oracle": same_runbook_as_oracle,
        "selected_runbook_source": source_paths.get(selected, ""),
        "candidate_runbooks": candidates,
        "route_score_margin": route_margin,
        "route_confidence": route_confidence,
        "expected_decision": case.expected_decision,
        "selected_action": selected_action,
        "action_matches_oracle": selected_action == oracle_action,
        "oracle_limited": case.expected_decision != "resolve_shadow",
        "verdict": verdict,
        "route_correct": route_correct,
        "close_attempted": close_attempted,
        "close_precise": close_precise,
        "verifier_accept": verifier_accept,
        "required_resolution_terms": list(case.required_resolution_terms),
        "required_terms_present": required_hits,
        "required_term_recall": required_recall,
        "forbidden_terms_present": forbidden_hits,
        "shadow_resolution_draft": draft,
        "estimated_hybrid_usd": round(float(cost.get("estimated_usd") or 0.0), 6),
        "estimated_hybrid_tokens": {
            "input": int(cost.get("input_tokens") or 0),
            "cached_input": int(cost.get("cached_input_tokens") or 0),
            "output": int(cost.get("output_tokens") or 0),
        },
        "oracle_5_5_xhigh_usd": round(oracle_cost.estimated_usd, 6),
        "oracle_5_5_xhigh_tokens": {
            "input": oracle_cost.input_tokens,
            "cached_input": oracle_cost.cached_input_tokens,
            "output": oracle_cost.output_tokens,
        },
    }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


def _runbook_fit_policy(runbook: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if runbook == "ABSTAIN":
        return {
            "complexity": "clarify/hold",
            "minimum_worker": "Local deterministic/no model",
            "final_verifier": "none",
            "allowed_action": "ask_clarifying_questions",
            "close_authority": "no close",
        }
    if runbook in APPROVAL_ONLY_RUNBOOKS:
        return {
            "complexity": "approval-gated/high-authority",
            "minimum_worker": "Bedrock GPT OSS 120B high or Bedrock Kimi K2.5 high",
            "final_verifier": "Bedrock GPT-5.4 high",
            "allowed_action": "approval_stop_prepare_evidence",
            "close_authority": "human approval required",
        }
    average_input = (
        sum(int(row["oracle_5_5_xhigh_tokens"]["input"]) for row in rows) / len(rows)
        if rows
        else 0
    )
    evidence_heavy = (
        runbook
        in {
            "BR",
            "HCL",
            "HRB",
            "LOBM",
            "PFG",
            "PSM",
            "SDC",
            "TMD",
        }
        or average_input >= 120_000
    )
    if evidence_heavy:
        return {
            "complexity": "evidence-heavy safe/plan",
            "minimum_worker": "Bedrock Kimi K2.5 medium or Bedrock GPT OSS 120B high",
            "final_verifier": "Bedrock GPT-5.4 medium sampled",
            "allowed_action": "close_shadow_with_evidence when evidence complete",
            "close_authority": "safe close only; approval gates still apply",
        }
    return {
        "complexity": "routine safe runbook",
        "minimum_worker": "Bedrock GPT OSS 120B medium",
        "final_verifier": "none required; sampled Bedrock GPT-5.4 medium",
        "allowed_action": "close_shadow_with_evidence when evidence complete",
        "close_authority": "safe close",
    }


def build_runbook_fit_matrix(
    rows: list[dict[str, Any]], *, source_paths: dict[str, str]
) -> dict[str, Any]:
    expected_runbooks = [*sorted(RUNBOOK_RESOLUTION_TERMS), *CLARIFY_ONLY_RUNBOOKS]
    matrix_rows: list[dict[str, Any]] = []
    covered = 0
    for runbook in expected_runbooks:
        runbook_rows = [
            row
            for row in rows
            if row["oracle_runbook"] == runbook or runbook in row["acceptable_runbooks"]
        ]
        if runbook_rows:
            covered += 1
        route_ok = sum(1 for row in runbook_rows if row["same_runbook_as_oracle"])
        action_ok = sum(1 for row in runbook_rows if row["action_matches_oracle"])
        accepted = sum(1 for row in runbook_rows if row["verifier_accept"])
        overreach = sum(1 for row in runbook_rows if row["forbidden_terms_present"])
        support_level = (
            "measured"
            if runbook_rows
            else "uncovered-needs-real-jira-or-synthetic-case"
        )
        policy = _runbook_fit_policy(runbook, runbook_rows)
        matrix_rows.append(
            {
                "runbook": runbook,
                "support_level": support_level,
                "case_count": len(runbook_rows),
                "ticket_ids": [str(row["ticket_id"]) for row in runbook_rows],
                "route_precision": _ratio(route_ok, len(runbook_rows)),
                "action_precision": _ratio(action_ok, len(runbook_rows)),
                "verifier_accept_rate": _ratio(accepted, len(runbook_rows)),
                "overreach_count": overreach,
                "approval_only": runbook in APPROVAL_ONLY_RUNBOOKS,
                "source_path": source_paths.get(runbook, ""),
                **policy,
            }
        )
    missing = [row["runbook"] for row in matrix_rows if row["case_count"] == 0]
    return {
        "schema": "norman.gaphelp-runbook-fit-matrix.v1",
        "runbook_count": len(matrix_rows),
        "covered_runbook_count": covered,
        "coverage_rate": _ratio(covered, len(matrix_rows)),
        "missing_runbooks": missing,
        "approval_only_runbooks": list(APPROVAL_ONLY_RUNBOOKS),
        "clarify_only_runbooks": list(CLARIFY_ONLY_RUNBOOKS),
        "rows": matrix_rows,
    }


def _gate_metrics(
    rows: list[dict[str, Any]], expected_decision: str, action: str
) -> dict[str, Any]:
    expected = [row for row in rows if row["expected_decision"] == expected_decision]
    selected = [row for row in rows if row["selected_action"] == action]
    true_positive = [
        row
        for row in rows
        if row["expected_decision"] == expected_decision
        and row["selected_action"] == action
    ]
    false_positive = [
        row
        for row in rows
        if row["expected_decision"] != expected_decision
        and row["selected_action"] == action
    ]
    false_negative = [
        row
        for row in rows
        if row["expected_decision"] == expected_decision
        and row["selected_action"] != action
    ]
    return {
        "expected_count": len(expected),
        "selected_count": len(selected),
        "true_positive_count": len(true_positive),
        "false_positive_count": len(false_positive),
        "false_negative_count": len(false_negative),
        "precision": _ratio(len(true_positive), len(selected)),
        "recall": _ratio(len(true_positive), len(expected)),
        "false_positive_ticket_ids": [str(row["ticket_id"]) for row in false_positive],
        "false_negative_ticket_ids": [str(row["ticket_id"]) for row in false_negative],
    }


def build_helpdesk_precision_report(
    *, mirror_root: Path = DEFAULT_MIRROR_ROOT, case_limit: int | None = None
) -> dict[str, Any]:
    cases = list(HELP_DESK_CASES[: case_limit or DEFAULT_HELPDESK_BENCHMARK_CASES])
    source_paths = _runbook_paths(mirror_root)
    rows = [score_helpdesk_case(case, source_paths=source_paths) for case in cases]
    route_cases = [row for row in rows if row["expected_runbook"] != "ABSTAIN"]
    close_attempts = [row for row in rows if row["close_attempted"]]
    safe_expected_closes = [
        row for row in rows if row["expected_decision"] == "resolve_shadow"
    ]
    route_correct = sum(1 for row in route_cases if row["route_correct"])
    close_precise = sum(1 for row in close_attempts if row["close_precise"])
    verifier_accepts = sum(1 for row in rows if row["verifier_accept"])
    same_runbook_as_oracle = sum(1 for row in rows if row["same_runbook_as_oracle"])
    same_action_as_oracle = sum(1 for row in rows if row["action_matches_oracle"])
    oracle_parity = sum(
        1
        for row in rows
        if row["same_runbook_as_oracle"]
        and row["action_matches_oracle"]
        and row["verifier_accept"]
    )
    overreach_count = sum(1 for row in rows if row["forbidden_terms_present"])
    total_estimated = round(sum(float(row["estimated_hybrid_usd"]) for row in rows), 6)
    oracle_estimated = round(sum(float(row["oracle_5_5_xhigh_usd"]) for row in rows), 6)
    oracle_limited_count = sum(1 for row in rows if row["oracle_limited"])
    high_confidence_or_abstain = sum(
        1 for row in rows if row["route_confidence"] in {"high", "abstain"}
    )
    unsafe_final_closes = sum(
        1
        for row in rows
        if row["expected_decision"] != "resolve_shadow"
        and row["selected_action"] == "close_shadow_with_evidence"
    )
    local_zero_cost_abstains = sum(
        1
        for row in rows
        if row["expected_decision"] == "abstain_for_clarification"
        and float(row["estimated_hybrid_usd"]) == 0.0
    )
    approval_gate = _gate_metrics(
        rows, "approval_stop", "approval_stop_prepare_evidence"
    )
    clarify_gate = _gate_metrics(
        rows, "abstain_for_clarification", "ask_clarifying_questions"
    )
    runbook_fit = build_runbook_fit_matrix(rows, source_paths=source_paths)
    unresolved = [
        row["ticket_id"]
        for row in rows
        if row["verdict"]
        not in {"would_close_shadow", "approval_stop", "abstain_correct"}
    ]
    return {
        "schema": "norman.gaphelp-helpdesk-runbook-precision.v2",
        "source_root": str(mirror_root),
        "case_count": len(rows),
        "route_case_count": len(route_cases),
        "safe_expected_close_count": len(safe_expected_closes),
        "close_attempt_count": len(close_attempts),
        "route_precision": round(route_correct / len(route_cases), 4)
        if route_cases
        else 1.0,
        "resolution_precision": round(close_precise / len(close_attempts), 4)
        if close_attempts
        else 1.0,
        "safe_close_coverage": round(close_precise / len(safe_expected_closes), 4)
        if safe_expected_closes
        else 1.0,
        "verifier_accept_rate": round(verifier_accepts / len(rows), 4) if rows else 1.0,
        "same_runbook_as_oracle_rate": round(same_runbook_as_oracle / len(rows), 4)
        if rows
        else 1.0,
        "same_action_as_oracle_rate": round(same_action_as_oracle / len(rows), 4)
        if rows
        else 1.0,
        "oracle_result_parity_rate": round(oracle_parity / len(rows), 4)
        if rows
        else 1.0,
        "oracle_limited_count": oracle_limited_count,
        "overreach_count": overreach_count,
        "unsafe_final_close_count": unsafe_final_closes,
        "local_zero_cost_abstain_count": local_zero_cost_abstains,
        "approval_gate": approval_gate,
        "clarify_gate": clarify_gate,
        "runbook_fit_matrix": runbook_fit,
        "estimated_hybrid_usd": total_estimated,
        "oracle_5_5_xhigh_usd": oracle_estimated,
        "hybrid_vs_oracle_savings_rate": round(
            1.0 - total_estimated / oracle_estimated, 4
        )
        if oracle_estimated
        else 0.0,
        "unresolved_ticket_ids": unresolved,
        "runbook_mismatch_ticket_ids": [
            row["ticket_id"] for row in rows if not row["same_runbook_as_oracle"]
        ],
        "action_mismatch_ticket_ids": [
            row["ticket_id"] for row in rows if not row["action_matches_oracle"]
        ],
        "better_faster_cheaper_safer": {
            "better": {
                "same_runbook_as_oracle_rate": round(
                    same_runbook_as_oracle / len(rows), 4
                )
                if rows
                else 1.0,
                "same_action_as_oracle_rate": round(
                    same_action_as_oracle / len(rows), 4
                )
                if rows
                else 1.0,
                "oracle_result_parity_rate": round(oracle_parity / len(rows), 4)
                if rows
                else 1.0,
            },
            "faster": {
                "high_confidence_or_abstain_rate": round(
                    high_confidence_or_abstain / len(rows), 4
                )
                if rows
                else 1.0,
                "local_zero_cost_abstain_count": local_zero_cost_abstains,
            },
            "cheaper": {
                "estimated_hybrid_usd": total_estimated,
                "oracle_5_5_xhigh_usd": oracle_estimated,
                "hybrid_vs_oracle_savings_rate": round(
                    1.0 - total_estimated / oracle_estimated, 4
                )
                if oracle_estimated
                else 0.0,
            },
            "safer": {
                "overreach_count": overreach_count,
                "unsafe_final_close_count": unsafe_final_closes,
                "oracle_limited_count": oracle_limited_count,
            },
        },
        "rows": rows,
        "interpretation": {
            "route_precision": "selected primary runbook matches the expected route or allowed secondary route",
            "resolution_precision": "shadow close attempts that selected the right runbook, included every required evidence term, avoided forbidden actions, and did not cross approval/block gates",
            "safe_close_coverage": "safe help-desk tickets that the hybrid policy would try to close in shadow",
            "verifier_accept_rate": "tickets where the verifier would accept close, approval stop, or abstain behavior",
            "same_runbook_as_oracle_rate": "hybrid-selected runbook matches the 5.5 xhigh oracle route, counting intentional abstain as a route",
            "same_action_as_oracle_rate": "hybrid-selected action matches the 5.5 xhigh oracle action: close, approval stop, or clarify",
            "oracle_result_parity_rate": "same runbook, same action, and verifier-accepted behavior versus the 5.5 xhigh oracle",
        },
    }


def build_benchmark_readiness_assessment(
    *,
    helpdesk_precision: dict[str, Any],
    model_matrix: dict[str, Any],
    threshold_matrix: dict[str, Any],
    bedrock_role_split: dict[str, Any],
    live_proof_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runbook_fit = helpdesk_precision["runbook_fit_matrix"]
    approval_gate = helpdesk_precision["approval_gate"]
    clarify_gate = helpdesk_precision["clarify_gate"]
    missing_runbooks = list(runbook_fit["missing_runbooks"])
    live_proof_report = live_proof_report or build_live_proof_report([])
    live_summary = live_proof_report["summary"]
    live_runs = int(live_summary["live_runs"])
    live_successes = int(live_summary["successful_runs"])
    live_status = "not_proven"
    live_evidence = "this report has no attached live model/provider receipts"
    live_gap = (
        "needs Bedrock canary runs with elapsed time, provider errors, retries, "
        "and output deltas"
    )
    if live_successes:
        live_status = (
            "single_canary_observed" if live_successes == 1 else "canary_observed"
        )
        live_evidence = (
            f"{live_successes}/{live_runs} live canaries succeeded; "
            f"{float(live_summary['expected_behavior_pass_rate']) * 100:.1f}% "
            f"matched expected safe behavior; {int(live_summary['observed_total_tokens'])} "
            f"observed tokens; p50 elapsed {float(live_summary['median_elapsed_seconds']):.1f}s"
        )
        live_gap = (
            "needs more models/cases, provider error samples, and repeated runs before "
            "using this as a production reliability claim"
        )
    dimensions = {
        "pricing_catalog": {
            "status": "shadow_ready",
            "evidence": (
                f"{model_matrix['model_count']} model rows with public-rate-card "
                f"pricing, {threshold_matrix['candidate_count']} candidate profiles, "
                "and current Bedrock GPT-5.4/GPT-5.5 context metadata"
            ),
            "gap": "needs invoice reconciliation for actual account discounts/overrides",
        },
        "bedrock_first_routing": {
            "status": "shadow_ready",
            "evidence": (
                "Bedrock-preferred matrix filters direct OpenAI out of worker/final "
                f"selection; combined modeled spend ${float(bedrock_role_split['summary']['combined_total_usd']):.4f}"
            ),
            "gap": "runtime still needs live multi-lane orchestration/canary before autonomous use",
        },
        "runbook_route_precision": {
            "status": "shadow_ready",
            "evidence": (
                f"{float(helpdesk_precision['route_precision']) * 100:.1f}% route "
                f"precision over {helpdesk_precision['case_count']} curated cases"
            ),
            "gap": "needs labeled real Jira help-desk export, not only synthetic/curated cases",
        },
        "approval_and_clarify_gates": {
            "status": "shadow_ready",
            "evidence": (
                f"approval precision/recall {float(approval_gate['precision']) * 100:.1f}%/"
                f"{float(approval_gate['recall']) * 100:.1f}%; clarify precision/recall "
                f"{float(clarify_gate['precision']) * 100:.1f}%/{float(clarify_gate['recall']) * 100:.1f}%"
            ),
            "gap": "needs negative real-world examples where agents are tempted to over-close",
        },
        "runbook_coverage": {
            "status": "needs_more_cases" if missing_runbooks else "shadow_ready",
            "evidence": (
                f"{runbook_fit['covered_runbook_count']} of {runbook_fit['runbook_count']} "
                "runbooks have benchmark cases"
            ),
            "gap": (
                "missing cases: " + ", ".join(missing_runbooks[:12])
                if missing_runbooks
                else "none"
            ),
        },
        "live_latency_reliability": {
            "status": live_status,
            "evidence": live_evidence,
            "gap": live_gap,
        },
        "real_jira_truth_set": {
            "status": "not_proven",
            "evidence": "no labeled real Jira/helpdesk export was attached",
            "gap": "needs real tickets labeled with expected runbook, action, approval, and resolution outcome",
        },
    }
    fully_figured_out = False
    observed_live = live_successes > 0
    return {
        "schema": "norman.gaphelp-benchmark-readiness.v1",
        "figured_out": fully_figured_out,
        "status": (
            "shadow_plus_live_canary_not_jira_truth"
            if observed_live
            else "shadow_ready_not_live_truth"
        ),
        "answer": (
            "No: the benchmark/tooling now has shadow routing plus at least one "
            "live Bedrock canary, but still lacks a labeled real Jira truth set "
            "and repeated live reliability samples."
            if observed_live
            else "No: the benchmark/tooling is strong enough for shadow routing and "
            "Bedrock-first cost planning, but not yet enough to claim real Jira "
            "production precision."
        ),
        "dimensions": dimensions,
        "next_required_evidence": [
            "import a labeled real Jira/helpdesk ticket sample with expected runbook, action, and approval outcome",
            "run more Bedrock-only live canaries that record latency, tokens, provider errors, retries, and model deltas",
            "add machine-readable runbook metadata for authority, evidence requirements, allowed actions, worker tier, and verifier tier",
            "compare Bedrock GPT-5.4 medium/high against GPT-5.5 xhigh on disagreement-heavy cases",
        ],
    }


def _candidate_by_id(
    issue_row: dict[str, Any] | None, candidate_id: str
) -> dict[str, Any] | None:
    if not issue_row:
        return None
    return next(
        (
            row
            for row in issue_row.get("candidate_rows", [])
            if row.get("candidate_id") == candidate_id
        ),
        None,
    )


def _scenario_unique_candidates(
    candidates: list[dict[str, Any] | None],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id or candidate_id in seen:
            continue
        seen.add(candidate_id)
        output.append(candidate)
    return output


def _scenario_autonomy_status(rollout_phase: str) -> str:
    if rollout_phase == "phase_0_local_deterministic":
        return "local_only"
    if rollout_phase == "phase_1_lower_model_shadow_canary":
        return "lower_model_shadow_ok"
    if rollout_phase == "phase_2_bedrock_5_4_verified_dry_run":
        return "dry_run_with_5_4_gate"
    if rollout_phase == "phase_3_operator_approved_apply_plan":
        return "operator_approval_required"
    if rollout_phase == "phase_4_bedrock_5_5_final_authority_hold":
        return "final_authority_hold"
    return "unknown"


def _scenario_phase_pipeline(
    *,
    scenario: GapHelpDeploymentScenario,
    issue_row: dict[str, Any] | None,
    role_split_row: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    minimum = (issue_row or {}).get("minimum_candidate")
    subagent = (role_split_row or {}).get("subagent_candidate")
    hint = _candidate_by_id(issue_row, scenario.candidate_hint_id)
    bedrock_5_4 = _candidate_by_id(issue_row, "bedrock_gpt_5_4_xhigh")
    bedrock_5_5 = _candidate_by_id(issue_row, "bedrock_gpt_5_5_xhigh")
    local = _candidate_by_id(issue_row, "local_deterministic")

    if scenario.rollout_phase == "phase_0_local_deterministic":
        return _scenario_unique_candidates([local or minimum])
    if scenario.rollout_phase == "phase_1_lower_model_shadow_canary":
        return _scenario_unique_candidates([hint or subagent or minimum])
    if scenario.rollout_phase == "phase_2_bedrock_5_4_verified_dry_run":
        return _scenario_unique_candidates([subagent, hint, bedrock_5_4])
    if scenario.rollout_phase == "phase_3_operator_approved_apply_plan":
        return _scenario_unique_candidates([subagent, hint, bedrock_5_4])
    if scenario.rollout_phase == "phase_4_bedrock_5_5_final_authority_hold":
        return _scenario_unique_candidates([subagent, bedrock_5_4, hint, bedrock_5_5])
    return _scenario_unique_candidates([hint or subagent or minimum])


def _scenario_cost_usd(pipeline: list[dict[str, Any]]) -> float:
    return round(sum(float(step.get("cost_usd") or 0.0) for step in pipeline), 6)


def _scenario_skill_refs(
    scenario: GapHelpDeploymentScenario, skill_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for skill_id in scenario.skill_ids:
        skill = skill_by_id.get(skill_id)
        if not skill:
            refs.append(
                {
                    "skill_id": skill_id,
                    "found": False,
                    "label": "",
                    "family": "",
                    "recommended_pipeline": [],
                    "recommended_pipeline_cost_usd": 0.0,
                }
            )
            continue
        refs.append(
            {
                "skill_id": skill_id,
                "found": True,
                "label": skill["label"],
                "family": skill["family"],
                "recommended_pipeline": skill.get("recommended_pipeline") or [],
                "recommended_pipeline_cost_usd": skill["recommended_pipeline_cost_usd"],
            }
        )
    return refs


def build_gaphelp_scenario_deployment_matrix(
    *,
    helpdesk_precision: dict[str, Any],
    threshold_matrix: dict[str, Any],
    foundational_skill_matrix: dict[str, Any],
    bedrock_role_split: dict[str, Any],
) -> dict[str, Any]:
    issue_by_id = {
        str(row["issue_id"]): row for row in threshold_matrix.get("rows", [])
    }
    skill_by_id = {
        str(row["skill_id"]): row for row in foundational_skill_matrix.get("rows", [])
    }
    role_split_by_id = {
        str(row["issue_id"]): row for row in bedrock_role_split.get("rows", [])
    }
    ticket_by_id = {
        str(row["ticket_id"]): row for row in helpdesk_precision.get("rows", [])
    }

    rows: list[dict[str, Any]] = []
    for scenario in GAPHELP_DEPLOYMENT_SCENARIOS:
        issue_row = issue_by_id.get(scenario.issue_class_id)
        role_row = role_split_by_id.get(scenario.issue_class_id)
        pipeline = _scenario_phase_pipeline(
            scenario=scenario,
            issue_row=issue_row,
            role_split_row=role_row,
        )
        baseline = _candidate_by_id(issue_row, "bedrock_gpt_5_5_xhigh")
        baseline_cost = float((baseline or {}).get("cost_usd") or 0.0)
        cost = _scenario_cost_usd(pipeline)
        known_tickets = [
            ticket_by_id[ticket_id]
            for ticket_id in scenario.ticket_ids
            if ticket_id in ticket_by_id
        ]
        helpdesk_parity = (
            _ratio(
                sum(
                    1
                    for ticket in known_tickets
                    if ticket.get("same_runbook_as_oracle")
                    and ticket.get("action_matches_oracle")
                    and ticket.get("verifier_accept")
                ),
                len(known_tickets),
            )
            if known_tickets
            else None
        )
        rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "label": scenario.label,
                "family": scenario.family,
                "owner_tui": scenario.owner_tui,
                "tenant_scope": scenario.tenant_scope,
                "issue_class_id": scenario.issue_class_id,
                "issue_class_label": str((issue_row or {}).get("label") or ""),
                "skill_refs": _scenario_skill_refs(scenario, skill_by_id),
                "ticket_ids": list(scenario.ticket_ids),
                "runbooks": list(scenario.runbooks),
                "rollout_phase": scenario.rollout_phase,
                "autonomy_status": _scenario_autonomy_status(scenario.rollout_phase),
                "deploy_candidate": scenario.deploy_candidate,
                "recommended_first_tui": scenario.recommended_first_tui,
                "pipeline": pipeline,
                "pipeline_candidate_ids": [
                    str(step.get("candidate_id") or "") for step in pipeline
                ],
                "pipeline_cost_usd": cost,
                "all_bedrock_5_5_xhigh_cost_usd": round(baseline_cost, 6),
                "savings_vs_all_bedrock_5_5_xhigh": (
                    round(1.0 - cost / baseline_cost, 4) if baseline_cost else 0.0
                ),
                "helpdesk_oracle_parity_rate": helpdesk_parity,
                "blocked_actions": list(scenario.blocked_actions),
                "evidence_required": list(scenario.evidence_required),
                "notes": scenario.notes,
            }
        )

    phase_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    owner_counts: dict[str, int] = {}
    for row in rows:
        phase_counts[str(row["rollout_phase"])] = (
            phase_counts.get(str(row["rollout_phase"]), 0) + 1
        )
        family_counts[str(row["family"])] = family_counts.get(str(row["family"]), 0) + 1
        owner_counts[str(row["owner_tui"])] = (
            owner_counts.get(str(row["owner_tui"]), 0) + 1
        )

    first = next((row for row in rows if row["recommended_first_tui"]), rows[0])
    first_gaphelp = next(
        (
            row
            for row in rows
            if row["family"] == "gaphelp_helpdesk" and row["deploy_candidate"]
        ),
        None,
    )
    deployable = [row for row in rows if row["deploy_candidate"]]
    final_holds = [
        row
        for row in rows
        if row["rollout_phase"] == "phase_4_bedrock_5_5_final_authority_hold"
    ]
    phase1 = [
        row
        for row in rows
        if row["rollout_phase"] == "phase_1_lower_model_shadow_canary"
    ]
    phase1_and_2 = [
        row
        for row in rows
        if row["rollout_phase"]
        in {
            "phase_1_lower_model_shadow_canary",
            "phase_2_bedrock_5_4_verified_dry_run",
        }
    ]

    def _slice_cost_summary(slice_rows: list[dict[str, Any]]) -> dict[str, Any]:
        pipeline_total = round(
            sum(float(row["pipeline_cost_usd"]) for row in slice_rows),
            6,
        )
        baseline_total = round(
            sum(float(row["all_bedrock_5_5_xhigh_cost_usd"]) for row in slice_rows),
            6,
        )
        return {
            "count": len(slice_rows),
            "pipeline_total_usd": pipeline_total,
            "all_bedrock_5_5_xhigh_total_usd": baseline_total,
            "savings_vs_all_bedrock_5_5_xhigh": (
                round(1.0 - pipeline_total / baseline_total, 4)
                if baseline_total
                else 0.0
            ),
        }

    total_cost = round(sum(float(row["pipeline_cost_usd"]) for row in rows), 6)
    total_baseline = round(
        sum(float(row["all_bedrock_5_5_xhigh_cost_usd"]) for row in rows),
        6,
    )
    return {
        "schema": "norman.gaphelp-scenario-deployment-matrix.v1",
        "evidence_level": (
            "shadow_heuristic with curated GapHelp oracle cases; deployable rows "
            "still require TUI canary receipts before live writes"
        ),
        "scenario_count": len(rows),
        "rows": rows,
        "summary": {
            "phase_counts": phase_counts,
            "family_counts": family_counts,
            "owner_tui_counts": owner_counts,
            "deploy_candidate_count": len(deployable),
            "lower_model_shadow_canary_count": len(phase1),
            "bedrock_5_5_final_hold_count": len(final_holds),
            "recommended_first_tui": first["owner_tui"],
            "recommended_first_tui_scenario": first["scenario_id"],
            "recommended_first_tui_reason": first["notes"],
            "first_gaphelp_tui": (first_gaphelp or {}).get("owner_tui", ""),
            "first_gaphelp_scenario": (first_gaphelp or {}).get("scenario_id", ""),
            "deploy_candidate_cost_summary": _slice_cost_summary(deployable),
            "phase_1_canary_cost_summary": _slice_cost_summary(phase1),
            "phase_1_2_dry_run_cost_summary": _slice_cost_summary(phase1_and_2),
            "deployment_order": [
                "compere phase-1: status/estimate/Keystone compare canary, no writes",
                "control-plane phase-1: GapHelp runbook route/evidence shadow, no ticket writes",
                "control-plane phase-2: 5.4-verified dry-run resolution packets",
                "webgoat and gold-book phase-2: selector/validator/code dry-runs with tests",
                "netops phase-4 only after operator approval and final-authority hold",
            ],
            "modeled_pipeline_total_usd": total_cost,
            "all_bedrock_5_5_xhigh_total_usd": total_baseline,
            "savings_vs_all_bedrock_5_5_xhigh": (
                round(1.0 - total_cost / total_baseline, 4) if total_baseline else 0.0
            ),
            "comfort_statement": (
                "Large worker portions can run on lower Bedrock models in shadow: "
                "status answers, route selection, evidence lookup, draft summaries, "
                "simple data operations, and code-draft suggestions. 5.4 should gate "
                "dry-run acceptance, tenant/purse checks, rollback plans, and data-fix "
                "explanations. 5.5 should remain a narrow final-authority hold."
            ),
        },
        "spec_changes_recommended": [
            "Add machine-readable runbook metadata for authority, allowed actions, evidence, worker tier, verifier tier, and tenant scope.",
            "Add per-turn estimate receipts: objective, skills, tools, model route, expected cost, expected timing, and final actuals.",
            "Log scenario IDs on benchmark, TUI status, and final outcome records so planned vs final estimates can be compared.",
            "Keep work-special and personal TUIs explicitly labeled in prompts, status snapshots, ledgers, and route policy.",
            "Require canary receipts before enabling any scenario beyond shadow/dry-run.",
        ],
        "blindspots_before_deploy": [
            "No labeled real Jira export is attached yet; curated cases are necessary but not sufficient.",
            "Provider latency/error/retry rates are still thin; the matrix has only bounded canary evidence.",
            "Runbook metadata is inferred from code and curated cases, not fully authoritative source-of-truth metadata.",
            "Lower-model pass rates are modeled from thresholds; they need paired model-output canaries by scenario.",
            "Live writes, BBS lifecycle changes, deploy/restart, access changes, and customer-visible data fixes remain approval-gated.",
        ],
    }


def _extract_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def load_live_proofs(paths: list[Path]) -> list[dict[str, Any]]:
    proofs: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"live proof must be a JSON object: {path}")
        payload = dict(payload)
        payload["source_path"] = str(path)
        proofs.append(payload)
    return proofs


def build_live_proof_report(proofs: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for proof in proofs:
        live_turn = (
            proof.get("live_turn") if isinstance(proof.get("live_turn"), dict) else {}
        )
        route_request = (
            proof.get("route_request")
            if isinstance(proof.get("route_request"), dict)
            else {}
        )
        after = proof.get("after") if isinstance(proof.get("after"), dict) else {}
        response = _extract_json_object(proof.get("response_preview"))
        response_action = str(response.get("action") or "").strip().lower()
        safe_non_close = not any(
            word in response_action for word in ("close", "resolve", "mutate", "write")
        )
        needs_clarification = bool(response.get("needs_clarification"))
        selected_runbook = str(response.get("selected_runbook") or "").strip()
        no_tools = int(live_turn.get("tool_event_count") or 0) == 0
        route_match = (
            str(after.get("last_runtime") or live_turn.get("runtime") or "")
            == str(route_request.get("runtime") or "")
            and str(after.get("last_model") or live_turn.get("model") or "")
            == str(route_request.get("model") or "")
            and str(
                after.get("last_service_tier") or live_turn.get("service_tier") or ""
            )
            == str(route_request.get("service_tier") or "")
        )
        success = (
            str(live_turn.get("state") or "") == "done"
            and not str(after.get("last_error") or "").strip()
            and int(live_turn.get("observed_total_tokens") or 0) > 0
        )
        expected_behavior_pass = (
            success
            and route_match
            and no_tools
            and bool(selected_runbook)
            and needs_clarification
            and safe_non_close
        )
        rows.append(
            {
                "run_id": str(proof.get("run_id") or ""),
                "source_path": str(proof.get("source_path") or ""),
                "surface": str(proof.get("surface") or ""),
                "runtime": str(
                    live_turn.get("runtime") or after.get("last_runtime") or ""
                ),
                "model": str(live_turn.get("model") or after.get("last_model") or ""),
                "service_tier": str(
                    live_turn.get("service_tier")
                    or after.get("last_service_tier")
                    or ""
                ),
                "route_match": route_match,
                "success": success,
                "expected_behavior_pass": expected_behavior_pass,
                "elapsed_seconds": int(live_turn.get("elapsed_seconds") or 0),
                "observed_input_tokens": int(
                    live_turn.get("observed_input_tokens") or 0
                ),
                "observed_cached_input_tokens": int(
                    live_turn.get("observed_cached_input_tokens") or 0
                ),
                "observed_output_tokens": int(
                    live_turn.get("observed_output_tokens") or 0
                ),
                "observed_reasoning_output_tokens": int(
                    live_turn.get("observed_reasoning_output_tokens") or 0
                ),
                "observed_total_tokens": int(
                    live_turn.get("observed_total_tokens") or 0
                ),
                "tool_event_count": int(live_turn.get("tool_event_count") or 0),
                "decision_count": int(live_turn.get("decision_count") or 0),
                "selected_runbook": selected_runbook,
                "action": response_action,
                "needs_clarification": needs_clarification,
                "needs_approval": bool(response.get("needs_approval")),
                "confidence": response.get("confidence"),
                "safe_next_step": str(response.get("safe_next_step") or ""),
                "last_error": str(after.get("last_error") or ""),
            }
        )

    successful = sum(1 for row in rows if row["success"])
    route_matches = sum(1 for row in rows if row["route_match"])
    expected_passes = sum(1 for row in rows if row["expected_behavior_pass"])
    elapsed = sorted(
        int(row["elapsed_seconds"]) for row in rows if row["elapsed_seconds"]
    )
    median_elapsed = elapsed[len(elapsed) // 2] if elapsed else 0
    return {
        "schema": "norman.gaphelp-live-proof-report.v1",
        "summary": {
            "live_runs": len(rows),
            "successful_runs": successful,
            "route_match_rate": _ratio(route_matches, len(rows)),
            "expected_behavior_pass_rate": _ratio(expected_passes, len(rows)),
            "observed_total_tokens": sum(
                int(row["observed_total_tokens"]) for row in rows
            ),
            "observed_output_tokens": sum(
                int(row["observed_output_tokens"]) for row in rows
            ),
            "observed_reasoning_output_tokens": sum(
                int(row["observed_reasoning_output_tokens"]) for row in rows
            ),
            "median_elapsed_seconds": median_elapsed,
        },
        "rows": rows,
        "interpretation": {
            "route_match_rate": "observed last runtime/model/tier matched the requested route",
            "expected_behavior_pass_rate": "live response stayed non-mutating, selected a runbook, requested missing evidence, and did not falsely close",
        },
    }


def _sum_cost(lines: list[CostLine]) -> dict[str, Any]:
    return {
        "input_tokens": sum(line.input_tokens for line in lines),
        "cached_input_tokens": sum(line.cached_input_tokens for line in lines),
        "output_tokens": sum(line.output_tokens for line in lines),
        "estimated_usd": round(sum(line.estimated_usd for line in lines), 6),
    }


def _select_safe(tickets: list[TicketShape], limit: int) -> list[TicketShape]:
    candidates = [ticket for ticket in tickets if _safe_candidate(ticket)]
    candidates.sort(key=lambda item: (-item.obviousness, item.input_tokens))
    return candidates[: max(0, limit)]


def evaluate_policy(
    policy_id: str,
    tickets: list[TicketShape],
    *,
    max_do: int,
    budget_usd: float,
) -> tuple[PolicyResult, list[CostLine], list[str]]:
    lines: list[CostLine] = []
    completed: list[str] = []
    skipped_budget = 0
    triaged = 0
    attempted = 0
    approval_stops = sum(1 for ticket in tickets if ticket.approval_required)
    blocked_stops = sum(1 for ticket in tickets if ticket.blocked)
    notes: list[str] = []

    if policy_id == "watch_only":
        notes.append("Metadata/status/BBS/inventory only; no model spend.")
        result = _result(
            policy_id,
            "Watch-only inventory loop",
            "Read ticket metadata and route/BBS state only.",
            tickets,
            lines,
            triaged=0,
            attempted=0,
            completed_shadow=0,
            approval_stops=approval_stops,
            blocked_stops=blocked_stops,
            skipped_budget=0,
            budget_usd=budget_usd,
            notes=tuple(notes),
        )
        return result, lines, completed

    if policy_id in {"cheap_triage_top5", "cheap_triage_top10"}:
        for ticket in tickets:
            line = triage_cost(ticket)
            if (
                sum(item.estimated_usd for item in lines) + line.estimated_usd
                <= budget_usd
            ):
                lines.append(line)
                triaged += 1
            else:
                skipped_budget += 1
        limit = 5 if policy_id == "cheap_triage_top5" else 10
        for ticket in _select_safe(tickets, min(limit, max_do)):
            candidate_lines = hybrid_cost(ticket)
            projected = sum(item.estimated_usd for item in lines + candidate_lines)
            if projected > budget_usd:
                skipped_budget += 1
                continue
            lines.extend(candidate_lines)
            attempted += 1
            completed.append(ticket.ticket_id)
        notes.append(
            "Triage all affordable tickets with mini; do only top safe tickets with hybrid verification."
        )
        return (
            _result(
                policy_id,
                "Mini triage -> hybrid top safe tickets",
                "Cheap first pass over backlog, then bounded hybrid execution for obvious safe work.",
                tickets,
                lines,
                triaged=triaged,
                attempted=attempted,
                completed_shadow=len(completed),
                approval_stops=approval_stops,
                blocked_stops=blocked_stops,
                skipped_budget=skipped_budget,
                budget_usd=budget_usd,
                notes=tuple(notes),
            ),
            lines,
            completed,
        )

    if policy_id == "local_prefilter_hybrid_top":
        for ticket in _select_safe(tickets, max_do):
            candidate_lines = hybrid_cost(ticket)
            projected = sum(item.estimated_usd for item in lines + candidate_lines)
            if projected > budget_usd:
                skipped_budget += 1
                continue
            lines.extend(candidate_lines)
            attempted += 1
            completed.append(ticket.ticket_id)
        notes.append(
            "Use local metadata/hash/runbook gates first; spend hybrid tokens only on selected changed safe tickets."
        )
        return (
            _result(
                policy_id,
                "Local prefilter -> hybrid selected tickets",
                "Always-on shape: deterministic backlog scan, then hybrid execution only for changed safe tickets.",
                tickets,
                lines,
                triaged=0,
                attempted=attempted,
                completed_shadow=len(completed),
                approval_stops=approval_stops,
                blocked_stops=blocked_stops,
                skipped_budget=skipped_budget,
                budget_usd=budget_usd,
                notes=tuple(notes),
            ),
            lines,
            completed,
        )

    if policy_id == "full_5_5_all_safe":
        for ticket in _select_safe(tickets, max_do):
            candidate_lines = full_5_5_cost(ticket)
            projected = sum(item.estimated_usd for item in lines + candidate_lines)
            if projected > budget_usd:
                skipped_budget += 1
                continue
            lines.extend(candidate_lines)
            attempted += 1
            completed.append(ticket.ticket_id)
        notes.append("Full 5.5 only for safe candidates; no cheap triage savings.")
        return (
            _result(
                policy_id,
                "Full OpenAI GPT-5.5 Flex on safe tickets",
                "High-confidence OpenAI Direct Flex baseline over safe tickets only.",
                tickets,
                lines,
                triaged=0,
                attempted=attempted,
                completed_shadow=len(completed),
                approval_stops=approval_stops,
                blocked_stops=blocked_stops,
                skipped_budget=skipped_budget,
                budget_usd=budget_usd,
                notes=tuple(notes),
            ),
            lines,
            completed,
        )

    if policy_id == "full_bedrock_5_5_all_safe":
        for ticket in _select_safe(tickets, max_do):
            candidate_lines = full_bedrock_5_5_cost(ticket)
            projected = sum(item.estimated_usd for item in lines + candidate_lines)
            if projected > budget_usd:
                skipped_budget += 1
                continue
            lines.extend(candidate_lines)
            attempted += 1
            completed.append(ticket.ticket_id)
        notes.append(
            "Full Bedrock 5.5 baseline for safe candidates; uses us-east-2 Bedrock rate card and no cheap triage savings."
        )
        return (
            _result(
                policy_id,
                "Full Bedrock GPT-5.5 on-demand on safe tickets",
                "High-confidence Bedrock regional on-demand baseline over safe tickets only.",
                tickets,
                lines,
                triaged=0,
                attempted=attempted,
                completed_shadow=len(completed),
                approval_stops=approval_stops,
                blocked_stops=blocked_stops,
                skipped_budget=skipped_budget,
                budget_usd=budget_usd,
                notes=tuple(notes),
            ),
            lines,
            completed,
        )

    if policy_id == "batch_replay_all_safe":
        for ticket in _select_safe(tickets, max_do):
            candidate_lines = batch_replay_cost(ticket)
            projected = sum(item.estimated_usd for item in lines + candidate_lines)
            if projected > budget_usd:
                skipped_budget += 1
                continue
            lines.extend(candidate_lines)
            attempted += 1
            completed.append(ticket.ticket_id)
        notes.append(
            "Offline-only candidate; cheap but not suitable for interactive or urgent tickets."
        )
        return (
            _result(
                policy_id,
                "Nightly batch replay over safe tickets",
                "Lowest-cost offline replay with sampled verifier; not for live TUI answers.",
                tickets,
                lines,
                triaged=0,
                attempted=attempted,
                completed_shadow=len(completed),
                approval_stops=approval_stops,
                blocked_stops=blocked_stops,
                skipped_budget=skipped_budget,
                budget_usd=budget_usd,
                notes=tuple(notes),
            ),
            lines,
            completed,
        )

    raise ValueError(f"unknown policy: {policy_id}")


def _result(
    policy_id: str,
    label: str,
    description: str,
    tickets: list[TicketShape],
    lines: list[CostLine],
    *,
    triaged: int,
    attempted: int,
    completed_shadow: int,
    approval_stops: int,
    blocked_stops: int,
    skipped_budget: int,
    budget_usd: float,
    notes: tuple[str, ...],
) -> PolicyResult:
    totals = _sum_cost(lines)
    estimated = float(totals["estimated_usd"])
    return PolicyResult(
        policy_id=policy_id,
        label=label,
        description=description,
        backlog_seen=len(tickets),
        triaged=triaged,
        attempted=attempted,
        completed_shadow=completed_shadow,
        approval_stops=approval_stops,
        blocked_stops=blocked_stops,
        skipped_budget=skipped_budget,
        total_input_tokens=int(totals["input_tokens"]),
        total_cached_input_tokens=int(totals["cached_input_tokens"]),
        total_output_tokens=int(totals["output_tokens"]),
        estimated_usd=estimated,
        estimated_usd_if_hourly=round(estimated * 24, 6),
        estimated_usd_if_daily_once=estimated,
        steady_state_unchanged_usd=0.0,
        within_budget=estimated <= budget_usd,
        notes=notes,
    )


def build_report(
    *,
    ticket_count: int,
    max_do: int,
    budget_usd: float,
    policies: list[str] | None = None,
    mirror_root: Path = DEFAULT_MIRROR_ROOT,
    helpdesk_case_count: int = DEFAULT_HELPDESK_BENCHMARK_CASES,
    live_proofs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tickets = expand_backlog(ticket_count)
    helpdesk_precision = build_helpdesk_precision_report(
        mirror_root=mirror_root, case_limit=helpdesk_case_count
    )
    policy_ids = policies or [
        "watch_only",
        "local_prefilter_hybrid_top",
        "cheap_triage_top5",
        "cheap_triage_top10",
        "full_5_5_all_safe",
        "full_bedrock_5_5_all_safe",
        "batch_replay_all_safe",
    ]
    results: list[dict[str, Any]] = []
    details: dict[str, Any] = {}
    for policy_id in policy_ids:
        result, lines, completed = evaluate_policy(
            policy_id, tickets, max_do=max_do, budget_usd=budget_usd
        )
        results.append(asdict(result))
        details[policy_id] = {
            "cost_lines": [asdict(line) for line in lines],
            "completed_shadow_ticket_ids": completed,
        }

    interactive_affordable_done = [
        row
        for row in results
        if row["within_budget"]
        and row["completed_shadow"] > 0
        and row["policy_id"] != "batch_replay_all_safe"
    ]
    offline_affordable_done = [
        row for row in results if row["within_budget"] and row["completed_shadow"] > 0
    ]
    interactive_recommended = min(
        interactive_affordable_done,
        key=lambda row: (
            -(int(row["completed_shadow"])),
            float(row["estimated_usd"]),
        ),
        default=next(row for row in results if row["policy_id"] == "watch_only"),
    )
    offline_recommended = min(
        offline_affordable_done,
        key=lambda row: (
            -(int(row["completed_shadow"])),
            float(row["estimated_usd"]),
        ),
        default=next(row for row in results if row["policy_id"] == "watch_only"),
    )
    safe_candidates = sum(1 for ticket in tickets if _safe_candidate(ticket))
    approval_or_blocked = sum(
        1 for ticket in tickets if ticket.approval_required or ticket.blocked
    )
    model_matrix = build_model_capability_price_matrix(
        tickets=tickets,
        max_do=max_do,
        helpdesk_case_count=helpdesk_case_count,
    )
    threshold_matrix = build_control_plane_threshold_matrix(model_matrix)
    foundational_skill_matrix = build_foundational_skill_matrix(model_matrix)
    tui_operator_workflow_matrix = build_tui_operator_workflow_matrix(
        foundational_skill_matrix
    )
    role_split_matrix = build_role_split_matrix(threshold_matrix)
    bedrock_role_split_matrix = build_role_split_matrix(
        threshold_matrix, provider_preference="bedrock"
    )
    live_proof_report = build_live_proof_report(live_proofs or [])
    readiness_assessment = build_benchmark_readiness_assessment(
        helpdesk_precision=helpdesk_precision,
        model_matrix=model_matrix,
        threshold_matrix=threshold_matrix,
        bedrock_role_split=bedrock_role_split_matrix,
        live_proof_report=live_proof_report,
    )
    scenario_deployment_matrix = build_gaphelp_scenario_deployment_matrix(
        helpdesk_precision=helpdesk_precision,
        threshold_matrix=threshold_matrix,
        foundational_skill_matrix=foundational_skill_matrix,
        bedrock_role_split=bedrock_role_split_matrix,
    )
    return {
        "schema": "norman.gaphelp-ticket-loop-shadow.v1",
        "generated_at": int(time.time()),
        "dry_run_only": True,
        "model_calls_executed": 0,
        "ticket_count": len(tickets),
        "safe_candidate_count": safe_candidates,
        "approval_or_blocked_count": approval_or_blocked,
        "budget_usd": budget_usd,
        "max_do": max_do,
        "rate_card_comparison": build_rate_card_comparison(),
        "model_capability_price_matrix": model_matrix,
        "control_plane_threshold_matrix": threshold_matrix,
        "foundational_skill_matrix": foundational_skill_matrix,
        "tui_operator_workflow_matrix": tui_operator_workflow_matrix,
        "role_split_matrix": role_split_matrix,
        "bedrock_role_split_matrix": bedrock_role_split_matrix,
        "helpdesk_runbook_precision": helpdesk_precision,
        "gaphelp_scenario_deployment_matrix": scenario_deployment_matrix,
        "live_proof_report": live_proof_report,
        "benchmark_readiness_assessment": readiness_assessment,
        "policies": results,
        "details": details,
        "recommendation": {
            "policy_id": interactive_recommended["policy_id"],
            "label": interactive_recommended["label"],
            "estimated_usd": interactive_recommended["estimated_usd"],
            "completed_shadow": interactive_recommended["completed_shadow"],
            "why": (
                "Live-loop recommendation. Maximizes shadow completions under "
                "the configured budget while avoiding offline/batch policies and "
                "keeping repeated unchanged loops at zero model spend."
            ),
        },
        "offline_recommendation": {
            "policy_id": offline_recommended["policy_id"],
            "label": offline_recommended["label"],
            "estimated_usd": offline_recommended["estimated_usd"],
            "completed_shadow": offline_recommended["completed_shadow"],
            "why": "Cheapest high-throughput option when 24h/offline latency is acceptable.",
        },
        "always_on_shape": {
            "fast_loop": "watch_only every few minutes; zero model calls",
            "model_loop": "run only for new/changed tickets or operator-requested batch",
            "hard_stops": [
                "approval_required",
                "blocked",
                "state_change_required",
                "budget_exhausted",
            ],
            "cost_control": [
                "hash ticket body/runbook context and skip unchanged tickets",
                "mini triage before 5.5",
                "cap max_do per run",
                "write one internal cost record per shadow run",
            ],
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    helpdesk = report["helpdesk_runbook_precision"]
    rate_cards = report["rate_card_comparison"]
    model_matrix = report["model_capability_price_matrix"]
    threshold_matrix = report["control_plane_threshold_matrix"]
    foundational = report["foundational_skill_matrix"]
    tui_operator = report["tui_operator_workflow_matrix"]
    role_split = report["role_split_matrix"]
    bedrock_role_split = report["bedrock_role_split_matrix"]
    readiness = report["benchmark_readiness_assessment"]
    scenario_deploy = report["gaphelp_scenario_deployment_matrix"]
    live_proof = report["live_proof_report"]
    live_summary = live_proof["summary"]

    def _format_effort_row(row: dict[str, Any] | None) -> str:
        if not row:
            return "n/a"
        verdict = "pass" if row.get("meets_threshold") else "fail"
        cost = row.get("cost_usd")
        cost_text = "n/a" if cost is None else f"${float(cost):.4f}"
        accuracy = float(row.get("strict_accuracy") or 0.0) * 100
        return (
            f"{row.get('label')}: {verdict} {cost_text} "
            f"{accuracy:.1f}% {str(row.get('blocked_reason') or '').strip()}"
        ).strip()

    def _format_effort_ladder(ladder: dict[str, Any]) -> str:
        tiers = ladder.get("tiers") or {}
        return "<br>".join(
            f"{effort}: {_format_effort_row(tiers.get(effort))}"
            for effort in ("low", "medium", "high", "xhigh")
        )

    def _format_cheapest_effort(ladder: dict[str, Any]) -> str:
        cheapest = ladder.get("cheapest_passing")
        if not cheapest:
            return "none"
        return (
            f"{cheapest['label']} "
            f"({cheapest['reasoning_effort']}, ${float(cheapest['cost_usd']):.4f})"
        )

    def _format_pipeline(pipeline: list[dict[str, Any]]) -> str:
        labels = [
            str(step.get("label") or step.get("candidate_id") or "").replace("|", "/")
            for step in pipeline
        ]
        return " -> ".join(label for label in labels if label) or "none"

    bedrock_vs_standard = rate_cards["bedrock_vs_openai_standard"]
    bedrock_vs_flex = rate_cards["bedrock_vs_openai_flex"]
    bedrock_5_4_vs_5_5 = rate_cards["bedrock_gpt_5_4_vs_5_5"]
    lines = [
        "# GAPHELP Ticket Loop Shadow Benchmark",
        "",
        "Dry-run only. This benchmark does not call models, update tickets, ACK BBS, deploy, restart, or commit code.",
        "",
        "## Summary",
        "",
        f"- Tickets: {report['ticket_count']}",
        f"- Safe candidates: {report['safe_candidate_count']}",
        f"- Approval/blocked stops: {report['approval_or_blocked_count']}",
        f"- Budget: ${float(report['budget_usd']):.2f}",
        f"- Max shadow do per run: {report['max_do']}",
        f"- Recommended live policy: {report['recommendation']['label']} (${float(report['recommendation']['estimated_usd']):.4f}, {report['recommendation']['completed_shadow']} shadow completions)",
        f"- Recommended offline policy: {report['offline_recommendation']['label']} (${float(report['offline_recommendation']['estimated_usd']):.4f}, {report['offline_recommendation']['completed_shadow']} shadow completions)",
        f"- Help-desk route precision: {float(helpdesk['route_precision']) * 100:.1f}%",
        f"- Help-desk resolution precision: {float(helpdesk['resolution_precision']) * 100:.1f}%",
        f"- Help-desk verifier accept rate: {float(helpdesk['verifier_accept_rate']) * 100:.1f}%",
        f"- Help-desk oracle parity: {float(helpdesk['oracle_result_parity_rate']) * 100:.1f}%",
        f"- Help-desk hybrid estimated spend: ${float(helpdesk['estimated_hybrid_usd']):.4f}",
        f"- Help-desk 5.5 xhigh oracle spend: ${float(helpdesk['oracle_5_5_xhigh_usd']):.4f}",
        f"- Help-desk hybrid savings vs 5.5 xhigh oracle: {float(helpdesk['hybrid_vs_oracle_savings_rate']) * 100:.1f}%",
        f"- Bedrock GPT-5.5 on-demand vs OpenAI standard: {float(bedrock_vs_standard['input_ratio']):.2f}x input, {float(bedrock_vs_standard['output_ratio']):.2f}x output",
        f"- Bedrock GPT-5.5 on-demand vs OpenAI Flex: {float(bedrock_vs_flex['input_ratio']):.2f}x input, {float(bedrock_vs_flex['output_ratio']):.2f}x output",
        f"- Bedrock GPT-5.4 on-demand vs Bedrock GPT-5.5 on-demand: {float(bedrock_5_4_vs_5_5['input_ratio']):.2f}x input, {float(bedrock_5_4_vs_5_5['output_ratio']):.2f}x output",
        f"- Foundational skill delegated Bedrock pipeline: ${float(foundational['summary']['recommended_bedrock_pipeline_total_usd']):.4f} vs all Bedrock 5.5 xhigh ${float(foundational['summary']['all_bedrock_5_5_xhigh_total_usd']):.4f} ({float(foundational['summary']['savings_vs_all_bedrock_5_5_xhigh']) * 100:.1f}% savings)",
        f"- TUI operator workflow pipeline: ${float(tui_operator['summary']['recommended_bedrock_pipeline_total_usd']):.4f} vs all Bedrock 5.5 xhigh ${float(tui_operator['summary']['all_bedrock_5_5_xhigh_total_usd']):.4f} ({float(tui_operator['summary']['savings_vs_all_bedrock_5_5_xhigh']) * 100:.1f}% savings)",
        f"- Role-split modeled spend across issue classes: ${float(role_split['summary']['combined_total_usd']):.4f} (${float(role_split['summary']['subagent_total_usd']):.4f} subagent + ${float(role_split['summary']['final_total_usd']):.4f} final/verifier)",
        f"- Bedrock-preferred role-split modeled spend: ${float(bedrock_role_split['summary']['combined_total_usd']):.4f} (${float(bedrock_role_split['summary']['subagent_total_usd']):.4f} subagent + ${float(bedrock_role_split['summary']['final_total_usd']):.4f} final/verifier)",
        f"- Scenario deployment matrix: {scenario_deploy['scenario_count']} scenarios, {scenario_deploy['summary']['deploy_candidate_count']} deploy candidates, first TUI `{scenario_deploy['summary']['recommended_first_tui']}`, first GapHelp TUI `{scenario_deploy['summary']['first_gaphelp_tui']}`",
        f"- Scenario pipeline spend: ${float(scenario_deploy['summary']['modeled_pipeline_total_usd']):.4f} vs all Bedrock 5.5 xhigh ${float(scenario_deploy['summary']['all_bedrock_5_5_xhigh_total_usd']):.4f} ({float(scenario_deploy['summary']['savings_vs_all_bedrock_5_5_xhigh']) * 100:.1f}% savings)",
        f"- Deploy-candidate scenario spend: ${float(scenario_deploy['summary']['deploy_candidate_cost_summary']['pipeline_total_usd']):.4f} vs all Bedrock 5.5 xhigh ${float(scenario_deploy['summary']['deploy_candidate_cost_summary']['all_bedrock_5_5_xhigh_total_usd']):.4f} ({float(scenario_deploy['summary']['deploy_candidate_cost_summary']['savings_vs_all_bedrock_5_5_xhigh']) * 100:.1f}% savings)",
        f"- Phase-1 lower-model canary spend: ${float(scenario_deploy['summary']['phase_1_canary_cost_summary']['pipeline_total_usd']):.4f} vs all Bedrock 5.5 xhigh ${float(scenario_deploy['summary']['phase_1_canary_cost_summary']['all_bedrock_5_5_xhigh_total_usd']):.4f} ({float(scenario_deploy['summary']['phase_1_canary_cost_summary']['savings_vs_all_bedrock_5_5_xhigh']) * 100:.1f}% savings)",
        f"- Attached live proof runs: {live_summary['live_runs']} ({live_summary['successful_runs']} successful, {float(live_summary['expected_behavior_pass_rate']) * 100:.1f}% expected-behavior pass)",
        f"- Benchmark readiness: {readiness['status']} — {readiness['answer']}",
        "",
        "## Benchmark Readiness",
        "",
        f"- Figured out: {readiness['figured_out']}",
        "",
        "| Dimension | Status | Evidence | Gap |",
        "|---|---|---|---|",
    ]
    for name, dimension in readiness["dimensions"].items():
        lines.append(
            "| {name} | {status} | {evidence} | {gap} |".format(
                name=str(name).replace("_", " ").replace("|", "/"),
                status=str(dimension["status"]).replace("|", "/"),
                evidence=str(dimension["evidence"]).replace("|", "/"),
                gap=str(dimension["gap"]).replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "Next required evidence:",
        ]
    )
    for item in readiness["next_required_evidence"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Scenario Deployment Matrix",
            "",
            f"- Evidence level: {scenario_deploy['evidence_level']}",
            f"- Scenarios: {scenario_deploy['scenario_count']}",
            f"- Deploy candidates: {scenario_deploy['summary']['deploy_candidate_count']}",
            f"- Lower-model shadow canaries: {scenario_deploy['summary']['lower_model_shadow_canary_count']}",
            f"- Bedrock 5.5 final-authority holds: {scenario_deploy['summary']['bedrock_5_5_final_hold_count']}",
            f"- Recommended first TUI: `{scenario_deploy['summary']['recommended_first_tui']}` via `{scenario_deploy['summary']['recommended_first_tui_scenario']}`",
            f"- First GapHelp TUI: `{scenario_deploy['summary']['first_gaphelp_tui']}` via `{scenario_deploy['summary']['first_gaphelp_scenario']}`",
            f"- Deploy-candidate savings vs all Bedrock 5.5 xhigh: {float(scenario_deploy['summary']['deploy_candidate_cost_summary']['savings_vs_all_bedrock_5_5_xhigh']) * 100:.1f}%",
            f"- Phase-1 canary savings vs all Bedrock 5.5 xhigh: {float(scenario_deploy['summary']['phase_1_canary_cost_summary']['savings_vs_all_bedrock_5_5_xhigh']) * 100:.1f}%",
            f"- Policy: {scenario_deploy['summary']['comfort_statement']}",
            "",
            "Deployment order:",
        ]
    )
    for item in scenario_deploy["summary"]["deployment_order"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "| Scenario | Family | TUI | Scope | Phase | Autonomy | Pipeline | Cost | vs 5.5 | Tickets | Runbooks | Blocked Actions |",
            "|---|---|---|---|---|---|---|---:|---:|---|---|---|",
        ]
    )
    for row in scenario_deploy["rows"]:
        lines.append(
            "| {scenario} | {family} | {tui} | {scope} | {phase} | {autonomy} | {pipeline} | ${cost:.4f} | {savings:.1f}% | {tickets} | {runbooks} | {blocked} |".format(
                scenario=str(row["label"]).replace("|", "/"),
                family=str(row["family"]).replace("|", "/"),
                tui=str(row["owner_tui"]).replace("|", "/"),
                scope=str(row["tenant_scope"]).replace("|", "/"),
                phase=str(row["rollout_phase"]).replace("|", "/"),
                autonomy=str(row["autonomy_status"]).replace("|", "/"),
                pipeline=_format_pipeline(row.get("pipeline") or []).replace("|", "/"),
                cost=float(row["pipeline_cost_usd"]),
                savings=float(row["savings_vs_all_bedrock_5_5_xhigh"]) * 100,
                tickets=", ".join(str(item) for item in row["ticket_ids"]) or "n/a",
                runbooks=", ".join(str(item) for item in row["runbooks"]) or "n/a",
                blocked=", ".join(str(item) for item in row["blocked_actions"]).replace(
                    "|", "/"
                ),
            )
        )
    lines.extend(
        [
            "",
            "Recommended spec/tooling changes:",
        ]
    )
    for item in scenario_deploy["spec_changes_recommended"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "Blind spots before deploy:",
        ]
    )
    for item in scenario_deploy["blindspots_before_deploy"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Live Provider Proof",
            "",
            "Attached receipts only. Report generation remains dry-run; the live call happened before this report was built.",
            "",
            f"- Live runs: {live_summary['live_runs']}",
            f"- Successful runs: {live_summary['successful_runs']}",
            f"- Route match rate: {float(live_summary['route_match_rate']) * 100:.1f}%",
            f"- Expected behavior pass rate: {float(live_summary['expected_behavior_pass_rate']) * 100:.1f}%",
            f"- Observed tokens: {int(live_summary['observed_total_tokens']):,} total, {int(live_summary['observed_output_tokens']):,} output, {int(live_summary['observed_reasoning_output_tokens']):,} reasoning",
            f"- Median elapsed: {float(live_summary['median_elapsed_seconds']):.1f}s",
            "",
            "| Run | Route | Tier | Seconds | Tokens | Tools | Decision | Safe Behavior | Runbook | Action | Clarify |",
            "|---|---|---|---:|---:|---:|---:|---|---|---|---|",
        ]
    )
    for row in live_proof["rows"]:
        route = "/".join(
            part
            for part in [
                str(row.get("runtime") or ""),
                str(row.get("model") or ""),
            ]
            if part
        )
        lines.append(
            "| {run} | {route} | {tier} | {seconds} | {tokens} | {tools} | {decision} | {safe} | {runbook} | {action} | {clarify} |".format(
                run=str(row.get("run_id") or "").replace("|", "/"),
                route=route.replace("|", "/"),
                tier=str(row.get("service_tier") or "").replace("|", "/"),
                seconds=int(row.get("elapsed_seconds") or 0),
                tokens=int(row.get("observed_total_tokens") or 0),
                tools=int(row.get("tool_event_count") or 0),
                decision=int(row.get("decision_count") or 0),
                safe="yes" if row.get("expected_behavior_pass") else "no",
                runbook=str(row.get("selected_runbook") or "").replace("|", "/"),
                action=str(row.get("action") or "").replace("|", "/"),
                clarify="yes" if row.get("needs_clarification") else "no",
            )
        )
    lines.extend(
        [
            "",
            "## Rate Card Comparison",
            "",
            rate_cards["benchmark_warning"],
            "",
            "| Route | Input / 1M | Cached Input / 1M | Output / 1M |",
            "|---|---:|---:|---:|",
        ]
    )
    for label, card in rate_cards["rate_cards_usd_per_1m"].items():
        lines.append(
            "| {label} | ${input:.4f} | ${cached:.4f} | ${output:.4f} |".format(
                label=label.replace("_", " "),
                input=float(card["input"]),
                cached=float(card["cached_input"]),
                output=float(card["output"]),
            )
        )
    lines.extend(
        [
            "",
            "- " + str(bedrock_vs_standard["summary"]),
            "- " + str(bedrock_vs_flex["summary"]),
            "- " + str(bedrock_5_4_vs_5_5["summary"]),
            "",
            "## Model Capability / Price Matrix",
            "",
            f"- Price sources checked: {model_matrix['source_checked_on']}",
            f"- Model rows: {model_matrix['model_count']}",
            f"- Cost baseline: {model_matrix['findings']['frontier_fast_cost_baseline']}",
            f"- Cheapest full-safe route in this shadow shape: `{model_matrix['findings']['cheapest_full_safe_route']}`",
            f"- Cheapest frontier/strong route in this shadow shape: `{model_matrix['findings']['cheapest_frontier_or_strong_route']}`",
            f"- Fast/priority routes modeled: {', '.join(model_matrix['findings']['fast_routes']) or 'none'}",
            f"- Kimi route modeled: `{model_matrix['findings']['kimi_route'] or 'none'}`",
            f"- Warning: {model_matrix['findings']['warning']}",
            "",
            "| Route | Model | Surface | Tier | Timing | Capability | Max Complexity | Subagent Role | Final Role | Runbook Scope | Input / 1M | Cached / 1M | Output / 1M | Sample Ticket | Full Safe | Fast=100% | Savings vs Fast | vs 5.5 Flex | Roles |",
            "|---|---|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in model_matrix["rows"]:
        cached = row["cached_input_usd_per_1m"]
        role_text = ", ".join(str(item) for item in row["recommended_roles"])
        lines.append(
            "| {route} | {label} | {surface} | {tier} | {timing} | {capability} | {complexity} | {subagent} | {final} | {runbooks} | ${input:.4f} | {cached} | ${output:.4f} | ${sample:.4f} | ${full:.4f} | {fast_pct:.2f}% | {fast_save:.2f}% | {ratio:.3f}x | {roles} |".format(
                route=str(row["route_id"]).replace("|", "/"),
                label=str(row["label"]).replace("|", "/"),
                surface=str(row["provider_surface"]).replace("|", "/"),
                tier=str(row["service_tier"]).replace("|", "/"),
                timing=str(row["timing_target"]).replace("|", "/"),
                capability=str(row["capability_tier"]).replace("|", "/"),
                complexity=str(row["max_complexity"]).replace("|", "/"),
                subagent=str(row["subagent_role"]).replace("|", "/"),
                final=str(row["final_role"]).replace("|", "/"),
                runbooks=str(row["eligible_runbook_scope"]).replace("|", "/"),
                input=float(row["input_usd_per_1m"]),
                cached=(
                    "$" + f"{float(cached):.4f}"
                    if cached is not None
                    else "same as input"
                ),
                output=float(row["output_usd_per_1m"]),
                sample=float(row["sample_ticket_usd"]),
                full=float(row["full_safe_tickets_usd"]),
                fast_pct=float(row["full_safe_cost_percent_vs_frontier_fast"]),
                fast_save=float(row["full_safe_savings_percent_vs_frontier_fast"]),
                ratio=float(row["full_safe_ratio_vs_openai_5_5_flex"]),
                roles=role_text.replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "### Capability Notes",
            "",
        ]
    )
    for row in model_matrix["rows"]:
        if row["availability_notes"]:
            lines.append(
                "- `{route}`: {notes}".format(
                    route=str(row["route_id"]),
                    notes=str(row["availability_notes"]),
                )
            )
    lines.extend(
        [
            "",
            "## Foundational Skill Delegation Matrix",
            "",
            f"- Evidence level: {foundational['evidence_level']}",
            f"- Skills: {foundational['skill_count']}",
            f"- Candidate profiles: {foundational['candidate_count']}",
            f"- Delegated Bedrock pipeline total: ${float(foundational['summary']['recommended_bedrock_pipeline_total_usd']):.4f}",
            f"- All Bedrock 5.5 xhigh baseline: ${float(foundational['summary']['all_bedrock_5_5_xhigh_total_usd']):.4f}",
            f"- Savings vs all Bedrock 5.5 xhigh: {float(foundational['summary']['savings_vs_all_bedrock_5_5_xhigh']) * 100:.1f}%",
            f"- Cheap worker skills: {foundational['summary']['cheap_worker_count']}",
            f"- Bedrock 5.4 xhigh heavy-lift skills: {foundational['summary']['bedrock_5_4_xhigh_heavy_lift_count']}",
            f"- Bedrock 5.5 xhigh final-only skills: {foundational['summary']['bedrock_5_5_xhigh_final_count']}",
            f"- Policy: {foundational['summary']['recommended_policy']}",
            "",
            "| Skill | Family | Minimum Bedrock Worker | Pipeline | Strict Acc. | Cost | All 5.5 xhigh | Savings | 5.5 Final? | Notes |",
            "|---|---|---|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in foundational["rows"]:
        minimum = row.get("minimum_bedrock") or row.get("minimum_any") or {}
        pipeline = row.get("recommended_pipeline") or []
        pipeline_text = " -> ".join(
            str(step.get("label") or step.get("candidate_id") or "").replace("|", "/")
            for step in pipeline
        )
        strict_accuracy = float(minimum.get("strict_accuracy") or 0.0) * 100
        lines.append(
            "| {skill} | {family} | {worker} | {pipeline} | {strict:.1f}% | ${cost:.4f} | ${baseline:.4f} | {savings:.1f}% | {final} | {notes} |".format(
                skill=str(row["label"]).replace("|", "/"),
                family=str(row["family"]).replace("|", "/"),
                worker=str(minimum.get("label") or "none").replace("|", "/"),
                pipeline=pipeline_text or "none",
                strict=strict_accuracy,
                cost=float(row["recommended_pipeline_cost_usd"]),
                baseline=float(row["all_bedrock_5_5_xhigh_cost_usd"]),
                savings=float(row["savings_vs_all_bedrock_5_5_xhigh"]) * 100,
                final="yes" if row.get("requires_5_5_verifier") else "no",
                notes=str(row["notes"]).replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## TUI Operator Workflow Matrix",
            "",
            f"- Evidence level: {tui_operator['evidence_level']}",
            f"- Workflows: {tui_operator['workflow_count']}",
            f"- Delegated Bedrock pipeline total: ${float(tui_operator['summary']['recommended_bedrock_pipeline_total_usd']):.4f}",
            f"- All Bedrock 5.5 xhigh baseline: ${float(tui_operator['summary']['all_bedrock_5_5_xhigh_total_usd']):.4f}",
            f"- Savings vs all Bedrock 5.5 xhigh: {float(tui_operator['summary']['savings_vs_all_bedrock_5_5_xhigh']) * 100:.1f}%",
            f"- Local-only workflows: {tui_operator['summary']['local_only_count']}; cheap-worker workflows: {tui_operator['summary']['cheap_worker_count']}; 5.4-gated workflows: {tui_operator['summary']['bedrock_5_4_gate_count']}; 5.5-final workflows: {tui_operator['summary']['bedrock_5_5_final_count']}",
            f"- Policy: {tui_operator['summary']['recommended_policy']}",
            "",
            "| Workflow | Family | Model Role | Autonomy | Pipeline | Cost | Savings | Strict Err. | Overreach | Notes |",
            "|---|---|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in tui_operator["rows"]:
        pipeline = row.get("recommended_pipeline") or []
        pipeline_text = " -> ".join(
            str(step.get("label") or step.get("candidate_id") or "").replace("|", "/")
            for step in pipeline
        )
        lines.append(
            "| {workflow} | {family} | {role} | {autonomy} | {pipeline} | ${cost:.4f} | {savings:.1f}% | {strict:.1f}% | {overreach:.1f}% | {notes} |".format(
                workflow=str(row["label"]).replace("|", "/"),
                family=str(row["family"]).replace("|", "/"),
                role=str(row["recommended_model_role"]).replace("|", "/"),
                autonomy=str(row["autonomy_status"]).replace("|", "/"),
                pipeline=pipeline_text or "none",
                cost=float(row["recommended_pipeline_cost_usd"]),
                savings=float(row["savings_vs_all_bedrock_5_5_xhigh"]) * 100,
                strict=float(row["strict_error_rate"]) * 100,
                overreach=float(row["overreach_risk"]) * 100,
                notes=str(row["notes"]).replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Control Plane Ticket Threshold Matrix",
            "",
            f"- Evidence level: {threshold_matrix['evidence_level']}",
            f"- Issue classes: {threshold_matrix['issue_class_count']}",
            f"- Candidate profiles: {threshold_matrix['candidate_count']}",
            f"- 5.4 medium same-enough cases: {threshold_matrix['summary']['gpt_5_4_medium_same_enough_count']}",
            f"- 5.4 medium passes-lower-confidence cases: {threshold_matrix['summary']['gpt_5_4_medium_passes_lower_confidence_count']}",
            f"- 5.4 medium not-enough cases: {threshold_matrix['summary']['gpt_5_4_medium_not_enough_count']}",
            f"- OpenAI 5.5 cheapest passing efforts: {threshold_matrix['summary']['gpt_5_5_openai_effort_minimum_counts']}",
            f"- OpenAI 5.5 priority/fast cheapest passing efforts: {threshold_matrix['summary']['gpt_5_5_openai_priority_effort_minimum_counts']}",
            f"- Bedrock 5.5 cheapest passing efforts: {threshold_matrix['summary']['gpt_5_5_bedrock_effort_minimum_counts']}",
            f"- Policy: {threshold_matrix['summary']['recommended_policy']}",
            "",
            "| Issue Class | Authority | Minimum Route | Est. Accuracy | Overreach | Cost | 5.4 Medium vs 5.5 xhigh | Notes |",
            "|---|---|---|---:|---:|---:|---|---|",
        ]
    )
    for row in threshold_matrix["rows"]:
        minimum = row["minimum_candidate"] or {}
        comparison = row["gpt_5_4_medium_comparison"]
        parity = comparison["parity_vs_5_5_xhigh"]
        savings = comparison["savings_vs_5_5_xhigh"]
        savings_text = "n/a" if savings is None else f"{float(savings) * 100:.1f}%"
        minimum_label = str(minimum.get("label") or "none").replace("|", "/")
        accuracy = float(minimum.get("strict_accuracy") or 0.0) * 100
        overreach = float(minimum.get("overreach_risk") or 0.0) * 100
        cost = float(minimum.get("cost_usd") or 0.0)
        lines.append(
            "| {issue} | {authority} | {minimum} | {accuracy:.1f}% | {overreach:.1f}% | ${cost:.4f} | {parity}; saves {savings} | {notes} |".format(
                issue=str(row["label"]).replace("|", "/"),
                authority=str(row["authority_level"]).replace("|", "/"),
                minimum=minimum_label,
                accuracy=accuracy,
                overreach=overreach,
                cost=cost,
                parity=str(parity).replace("|", "/"),
                savings=savings_text,
                notes=str(row["notes"]).replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Role Split / Pipeline Matrix",
            "",
            f"- Evidence level: {role_split['evidence_level']}",
            f"- Final/verifier-required classes: {role_split['summary']['final_required_count']}",
            f"- Subagent modeled total: ${float(role_split['summary']['subagent_total_usd']):.4f}",
            f"- Final/verifier modeled total: ${float(role_split['summary']['final_total_usd']):.4f}",
            f"- Policy: {role_split['summary']['recommended_code_shape']}",
            "",
            "| Issue Class | Complexity | Timing Policy | Cheap Subagent | Subagent Cost | Final / Verifier | Final Cost | Combined | Runbooks | Policy |",
            "|---|---|---|---|---:|---|---:|---:|---|---|",
        ]
    )
    for row in role_split["rows"]:
        subagent = row.get("subagent_candidate") or {}
        final = row.get("final_candidate") or {}
        lines.append(
            "| {issue} | {complexity} | {timing} | {subagent} | ${subcost:.4f} | {final} | ${finalcost:.4f} | ${combined:.4f} | {runbooks} | {policy} |".format(
                issue=str(row["label"]).replace("|", "/"),
                complexity=str(row["complexity"]).replace("|", "/"),
                timing=str(row["timing_policy"]).replace("|", "/"),
                subagent=str(subagent.get("label") or "none").replace("|", "/"),
                subcost=float(row["subagent_cost_usd"]),
                final=str(final.get("label") or "none required").replace("|", "/"),
                finalcost=float(row["final_cost_usd"]),
                combined=float(row["combined_cost_usd"]),
                runbooks=str(row["eligible_runbook_sample"]).replace("|", "/"),
                policy=str(row["policy"]).replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Bedrock-Preferred Role Split",
            "",
            "- Provider preference: `aws-bedrock`; local deterministic checks remain allowed.",
            f"- Final/verifier-required classes: {bedrock_role_split['summary']['final_required_count']}",
            f"- Bedrock subagent modeled total: ${float(bedrock_role_split['summary']['subagent_total_usd']):.4f}",
            f"- Bedrock final/verifier modeled total: ${float(bedrock_role_split['summary']['final_total_usd']):.4f}",
            f"- Bedrock combined modeled total: ${float(bedrock_role_split['summary']['combined_total_usd']):.4f}",
            f"- Policy: {bedrock_role_split['summary']['recommended_code_shape']}",
            "",
            "| Issue Class | Complexity | Timing Policy | Bedrock Subagent | Surface | Subagent Cost | Bedrock Final / Verifier | Surface | Final Cost | Combined | Runbooks | Policy |",
            "|---|---|---|---|---|---:|---|---|---:|---:|---|---|",
        ]
    )
    for row in bedrock_role_split["rows"]:
        subagent = row.get("subagent_candidate") or {}
        final = row.get("final_candidate") or {}
        lines.append(
            "| {issue} | {complexity} | {timing} | {subagent} | {subsurface} | ${subcost:.4f} | {final} | {finalsurface} | ${finalcost:.4f} | ${combined:.4f} | {runbooks} | {policy} |".format(
                issue=str(row["label"]).replace("|", "/"),
                complexity=str(row["complexity"]).replace("|", "/"),
                timing=str(row["timing_policy"]).replace("|", "/"),
                subagent=str(subagent.get("label") or "none").replace("|", "/"),
                subsurface=str(subagent.get("provider_surface") or "none").replace(
                    "|", "/"
                ),
                subcost=float(row["subagent_cost_usd"]),
                final=str(final.get("label") or "none required").replace("|", "/"),
                finalsurface=str(final.get("provider_surface") or "none").replace(
                    "|", "/"
                ),
                finalcost=float(row["final_cost_usd"]),
                combined=float(row["combined_cost_usd"]),
                runbooks=str(row["eligible_runbook_sample"]).replace("|", "/"),
                policy=str(row["policy"]).replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "### GPT-5.5 Effort Ladder",
            "",
            "| Issue Class | OpenAI 5.5 Flex Cheapest | OpenAI 5.5 Flex Detail | OpenAI 5.5 Priority Cheapest | OpenAI 5.5 Priority Detail | Bedrock 5.5 Cheapest | Bedrock 5.5 Detail |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for row in threshold_matrix["rows"]:
        ladders = row["gpt_5_5_effort_ladder"]
        openai_ladder = ladders["openai_direct_flex"]
        priority_ladder = ladders["openai_direct_priority"]
        bedrock_ladder = ladders["bedrock_ondemand"]
        lines.append(
            "| {issue} | {openai_cheapest} | {openai_detail} | {priority_cheapest} | {priority_detail} | {bedrock_cheapest} | {bedrock_detail} |".format(
                issue=str(row["label"]).replace("|", "/"),
                openai_cheapest=_format_cheapest_effort(openai_ladder).replace(
                    "|", "/"
                ),
                openai_detail=_format_effort_ladder(openai_ladder).replace("|", "/"),
                priority_cheapest=_format_cheapest_effort(priority_ladder).replace(
                    "|", "/"
                ),
                priority_detail=_format_effort_ladder(priority_ladder).replace(
                    "|", "/"
                ),
                bedrock_cheapest=_format_cheapest_effort(bedrock_ladder).replace(
                    "|", "/"
                ),
                bedrock_detail=_format_effort_ladder(bedrock_ladder).replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Help Desk Runbook Precision",
            "",
            f"- Source root: `{helpdesk['source_root']}`",
            f"- Cases: {helpdesk['case_count']}",
            f"- Route precision: {float(helpdesk['route_precision']) * 100:.1f}%",
            f"- Resolution precision: {float(helpdesk['resolution_precision']) * 100:.1f}%",
            f"- Safe close coverage: {float(helpdesk['safe_close_coverage']) * 100:.1f}%",
            f"- Verifier accept rate: {float(helpdesk['verifier_accept_rate']) * 100:.1f}%",
            f"- Same runbook as 5.5 xhigh oracle: {float(helpdesk['same_runbook_as_oracle_rate']) * 100:.1f}%",
            f"- Same action as 5.5 xhigh oracle: {float(helpdesk['same_action_as_oracle_rate']) * 100:.1f}%",
            f"- Full oracle result parity: {float(helpdesk['oracle_result_parity_rate']) * 100:.1f}%",
            f"- Oracle-limited tickets requiring approval or clarification: {helpdesk['oracle_limited_count']}",
            f"- Approval gate precision/recall: {float(helpdesk['approval_gate']['precision']) * 100:.1f}% / {float(helpdesk['approval_gate']['recall']) * 100:.1f}%",
            f"- Clarify gate precision/recall: {float(helpdesk['clarify_gate']['precision']) * 100:.1f}% / {float(helpdesk['clarify_gate']['recall']) * 100:.1f}%",
            f"- Runbook coverage: {helpdesk['runbook_fit_matrix']['covered_runbook_count']} / {helpdesk['runbook_fit_matrix']['runbook_count']} ({float(helpdesk['runbook_fit_matrix']['coverage_rate']) * 100:.1f}%)",
            f"- Overreach count: {helpdesk['overreach_count']}",
            f"- Unsafe final-close count: {helpdesk['unsafe_final_close_count']}",
            f"- Hybrid estimated spend: ${float(helpdesk['estimated_hybrid_usd']):.4f}",
            f"- 5.5 xhigh oracle spend: ${float(helpdesk['oracle_5_5_xhigh_usd']):.4f}",
            f"- Hybrid savings vs 5.5 xhigh oracle: {float(helpdesk['hybrid_vs_oracle_savings_rate']) * 100:.1f}%",
            f"- Unresolved: {', '.join(helpdesk['unresolved_ticket_ids']) or 'none'}",
            f"- Runbook mismatches: {', '.join(helpdesk['runbook_mismatch_ticket_ids']) or 'none'}",
            f"- Action mismatches: {', '.join(helpdesk['action_mismatch_ticket_ids']) or 'none'}",
            "",
            "| Ticket | Oracle Runbook | Selected | Oracle Action | Selected Action | Parity | Verdict | Confidence | Hybrid | 5.5 xhigh |",
            "|---|---|---|---|---|---|---|---|---:|---:|",
        ]
    )
    for row in helpdesk["rows"]:
        parity = (
            "yes"
            if row["same_runbook_as_oracle"] and row["action_matches_oracle"]
            else "no"
        )
        lines.append(
            "| {ticket} | {expected} | {selected} | {oracle_action} | {selected_action} | {parity} | {verdict} | {confidence} | ${cost:.4f} | ${oracle_cost:.4f} |".format(
                ticket=str(row["ticket_id"]).replace("|", "/"),
                expected=str(row["oracle_runbook"]).replace("|", "/"),
                selected=str(row["selected_runbook"]).replace("|", "/"),
                oracle_action=str(row["oracle_action"]).replace("_", " "),
                selected_action=str(row["selected_action"]).replace("_", " "),
                parity=parity,
                confidence=(
                    f"{row['route_confidence']} " f"(+{int(row['route_score_margin'])})"
                ),
                verdict=str(row["verdict"]).replace("|", "/"),
                cost=float(row["estimated_hybrid_usd"]),
                oracle_cost=float(row["oracle_5_5_xhigh_usd"]),
            )
        )
    lines.extend(
        [
            "",
            "### Runbook Fit Matrix",
            "",
            "| Runbook | Support | Cases | Route | Action | Accept | Worker | Final | Allowed Action |",
            "|---|---|---:|---:|---:|---:|---|---|---|",
        ]
    )
    for row in helpdesk["runbook_fit_matrix"]["rows"]:
        lines.append(
            "| {runbook} | {support} | {cases} | {route:.1f}% | {action:.1f}% | {accept:.1f}% | {worker} | {final} | {allowed} |".format(
                runbook=str(row["runbook"]).replace("|", "/"),
                support=str(row["support_level"]).replace("|", "/"),
                cases=int(row["case_count"]),
                route=float(row["route_precision"]) * 100,
                action=float(row["action_precision"]) * 100,
                accept=float(row["verifier_accept_rate"]) * 100,
                worker=str(row["minimum_worker"]).replace("|", "/"),
                final=str(row["final_verifier"]).replace("|", "/"),
                allowed=str(row["allowed_action"]).replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Policy Board",
            "",
            "| Policy | Triaged | Shadow Done | Stops | Skipped Budget | First-pass Cost | If Hourly | Steady Unchanged |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report["policies"]:
        stops = int(row["approval_stops"]) + int(row["blocked_stops"])
        lines.append(
            "| {label} | {triaged} | {done} | {stops} | {skipped} | ${cost:.4f} | ${hourly:.4f}/day | ${steady:.4f} |".format(
                label=row["label"],
                triaged=row["triaged"],
                done=row["completed_shadow"],
                stops=stops,
                skipped=row["skipped_budget"],
                cost=float(row["estimated_usd"]),
                hourly=float(row["estimated_usd_if_hourly"]),
                steady=float(row["steady_state_unchanged_usd"]),
            )
        )
    lines.extend(
        [
            "",
            "## Operating Shape",
            "",
            f"- Fast loop: {report['always_on_shape']['fast_loop']}",
            f"- Model loop: {report['always_on_shape']['model_loop']}",
            "- Hard stops: "
            + ", ".join(str(item) for item in report["always_on_shape"]["hard_stops"]),
            "- Cost controls: "
            + "; ".join(
                str(item) for item in report["always_on_shape"]["cost_control"]
            ),
            "",
            "## Cheap / Fast / Safe Implementation Changes",
            "",
            "- TUI routing: expose separate `subagent_model`, `final_model`, and `timing_lane` controls. Default to local watch -> cheap draft worker -> frontier verifier only when the issue class requires it.",
            "- TUI operator workflows: treat status answers, working-on recaps, plan/cost estimates, queue advice, undo/unwind gates, BBS close-loop choices, and tenant/purse checks as named skills with logged initial/planned/final estimates.",
            "- TUI timing: map quick operator responses to `priority` only for the final/verifier lane. Keep background ticket scans on local, flex, or batch lanes.",
            "- Runbook metadata: add machine-readable fields for `authority`, `allowed_actions`, `approval_required`, `required_evidence`, `state_change`, `eligible_worker_tiers`, and `verifier_tier`.",
            "- Runbook execution: cache the ticket body hash, runbook pack hash, and evidence hash. Skip model calls for unchanged tickets and rerun only the smallest invalidated stage.",
            "- Safety gates: drafts can recommend, but final close requires the issue-class verifier. Purse/seal/key/sword actions remain approval stops even when the model passes.",
            "- Benchmarking: keep Kimi and other planned lanes in shadow until tool execution, runbook parity, and close-authority behavior have measured canary data.",
            "",
            "## Notes",
            "",
            "- Hourly cost is shown as a worst-case anti-pattern. The intended all-day loop is watch-only until a ticket changes.",
            "- Shadow done means the ticket looked safe enough to draft/verify in a simulation. It is not a production ticket update.",
        ]
    )
    return "\n".join(lines) + "\n"


def _shadow_record(
    report: dict[str, Any], output_json: Path, ticket_id: str
) -> dict[str, Any]:
    recommendation = report["recommendation"]
    recommended_lines = (
        report.get("details", {})
        .get(str(recommendation["policy_id"]), {})
        .get("cost_lines", [])
    )
    usage = {
        "input_tokens": sum(
            int(row.get("input_tokens") or 0) for row in recommended_lines
        ),
        "cached_input_tokens": sum(
            int(row.get("cached_input_tokens") or 0) for row in recommended_lines
        ),
        "output_tokens": sum(
            int(row.get("output_tokens") or 0) for row in recommended_lines
        ),
    }
    digest = hashlib.sha256(
        json.dumps(
            {
                "ticket_id": ticket_id,
                "generated_at": report["generated_at"],
                "usage": usage,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:20]
    return {
        "schema": "norman.ticket-token-cost-record.v1",
        "generated_at": report["generated_at"],
        "id": f"ttc_{digest}",
        "ticket": {"id": ticket_id},
        "source": {
            "kind": "gaphelp-ticket-loop-shadow",
            "ref": str(output_json),
            "thread_id": "",
            "actor": "norman",
        },
        "architecture": {"mode": "shadow-policy-board"},
        "usage": {
            "runtime": "shadow",
            "model": "mixed-policy-estimate",
            "service_tier": "estimated",
            **usage,
            "reasoning_output_tokens": 0,
            "total_tokens": usage["input_tokens"] + usage["output_tokens"],
            "usage_event_count": 0,
        },
        "billing": {
            "estimate_label": "estimated USD; not invoice-reconciled",
            "price_basis": "mixed-openai-direct-flex-ratio",
            "price_source": "local deterministic policy simulation",
            "charge_ledger_kind": "shadow_api_rate_card_estimate",
            "charge_display_unit": "usd_equivalent",
            "charge_status": "not_invoice_reconciled",
            "cost_known": True,
        },
        "cost": {"estimated_usd": float(recommendation["estimated_usd"])},
        "notes": "Shadow benchmark recommendation only; no model calls executed.",
        "metadata": {
            "recommendation": recommendation,
            "ticket_count": report["ticket_count"],
            "budget_usd": report["budget_usd"],
            "model_calls_executed": report["model_calls_executed"],
        },
    }


def write_report(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    output_md.write_text(render_markdown(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Shadow benchmark GAPHELP-style ticket loop cost policies."
    )
    parser.add_argument("--ticket-count", type=int, default=100)
    parser.add_argument("--max-do", type=int, default=10)
    parser.add_argument("--budget-usd", type=float, default=5.0)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--ledger-jsonl", type=Path, default=DEFAULT_LEDGER_JSONL)
    parser.add_argument("--ticket-id", default="gaphelp-ticket-loop-shadow")
    parser.add_argument("--mirror-root", type=Path, default=DEFAULT_MIRROR_ROOT)
    parser.add_argument(
        "--helpdesk-case-count",
        type=int,
        default=DEFAULT_HELPDESK_BENCHMARK_CASES,
    )
    parser.add_argument(
        "--live-proof-json",
        action="append",
        default=[],
        type=Path,
        help="Attach an observed live canary receipt JSON. Can be passed multiple times.",
    )
    parser.add_argument("--write-ledger", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(
        ticket_count=args.ticket_count,
        max_do=args.max_do,
        budget_usd=args.budget_usd,
        mirror_root=args.mirror_root,
        helpdesk_case_count=args.helpdesk_case_count,
        live_proofs=load_live_proofs(args.live_proof_json),
    )
    write_report(report, args.output_json, args.output_md)
    if args.write_ledger:
        append_record(
            args.ledger_jsonl,
            _shadow_record(report, args.output_json, args.ticket_id),
        )
    print(json.dumps(report["recommendation"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
