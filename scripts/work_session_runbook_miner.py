#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_JSON = Path("/tmp/norman_tui_benchmarks/work_session_runbook_miner.json")
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_benchmarks/work_session_runbook_miner.md")
DEFAULT_CANDIDATE_DIR = Path(
    "/tmp/norman_tui_benchmarks/work_session_runbook_candidates"
)
MAX_SESSION_PROMPT_CHARS = 80_000
MAX_SESSION_RESPONSE_CHARS = 160_000


@dataclass(frozen=True)
class SessionTurn:
    turn_id: str
    source_path: str
    thread_id: str
    started_at: int
    model: str
    service_tier: str
    prompt: str
    response: str


@dataclass(frozen=True)
class RunbookPattern:
    pattern_id: str
    label: str
    domain: str
    family: str
    owner_tui: str
    tenant_boundary: str
    keywords: tuple[str, ...]
    min_keyword_hits: int
    runbook_outputs: tuple[str, ...]
    skill_outputs: tuple[str, ...]
    tool_outputs: tuple[str, ...]
    deterministic_validators: tuple[str, ...]
    lower_model_role: str
    final_model_gate: str
    live_authority: str
    hybridization: str
    benchmark_cases_to_add: tuple[str, ...]
    notes: str


REDACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[^\s,;]+"),
        "authorization=[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)\b(authorization|bearer|api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|cookie)\b\s*[:=]\s*[^\s,;]+"
        ),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(
            r"(?is)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----"
        ),
        "[PRIVATE_KEY_REDACTED]",
    ),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[AWS_ACCESS_KEY_REDACTED]"),
    (re.compile(r"\bASIA[0-9A-Z]{16}\b"), "[AWS_TEMP_KEY_REDACTED]"),
    (re.compile(r"\+1\d{10}\b"), "[PHONE_REDACTED]"),
    (
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
        "[EMAIL_REDACTED]",
    ),
)


RUNBOOK_PATTERNS: tuple[RunbookPattern, ...] = (
    RunbookPattern(
        pattern_id="tui_fleet_wedge_recovery",
        label="TUI fleet wedge detection and recovery",
        domain="tui-ops",
        family="runbook",
        owner_tui="control-plane/netops",
        tenant_boundary="work-special or personal, based on target TUI tenant",
        keywords=(
            "wedged",
            "tui_fleet_doctor",
            "tui_fleet_scorecard",
            "pending=false",
            "ssh banner",
            "root disk",
            "restart",
            "networking",
            "netops",
            "work-special",
        ),
        min_keyword_hits=2,
        runbook_outputs=(
            "tui-wedge-detection",
            "host-reachability-triage",
            "disk-pressure-recovery",
        ),
        skill_outputs=("tui-fleet-recovery",),
        tool_outputs=(
            "scripts/tui_fleet_doctor.py",
            "scripts/tui_fleet_scorecard.py",
            "scripts/tui_host_recovery.py",
        ),
        deterministic_validators=(
            "/api/status",
            "systemctl is-active",
            "df -h",
            "scorecard grade",
        ),
        lower_model_role="summarize doctor output, classify wedge type, draft recovery note",
        final_model_gate="Bedrock GPT-5.4 xhigh for ambiguous host/root recovery; operator approval before disruptive restart",
        live_authority="restart/cleanup/root actions require owner or explicit operator approval",
        hybridization="local probes first; low model summarizes; 5.4 verifies recovery plan",
        benchmark_cases_to_add=(
            "api-status stale but process healthy",
            "host reachable with SSH banner timeout",
            "disk full blocks sync/restart",
            "wrong DNS/tailnet record",
        ),
        notes="Strong candidate for deterministic tooling; the LLM should not be deciding from raw shell output alone.",
    ),
    RunbookPattern(
        pattern_id="bedrock_shortstop_diagnostics",
        label="Bedrock short-stop and context compression diagnostics",
        domain="model-routing",
        family="diagnostic",
        owner_tui="control-plane",
        tenant_boundary="work-special model fleet",
        keywords=(
            "short stopping",
            "short-stopping",
            "progress-only",
            "bedrock",
            "codex wrapper",
            "compact context",
            "context benchmark",
            "stream disconnected",
            "provider readiness",
        ),
        min_keyword_hits=2,
        runbook_outputs=("bedrock-shortstop-diagnosis", "context-pack-gate"),
        skill_outputs=("bedrock-routing-health",),
        tool_outputs=(
            "scripts/tui_bedrock_shortstop_benchmark.py",
            "scripts/tui_context_shadow_benchmark.py",
            "scripts/tui_provider_readiness_benchmark.py",
        ),
        deterministic_validators=(
            "provider event count",
            "empty/progress-only turn detector",
            "packed token delta",
        ),
        lower_model_role="classify known failure signatures and compare benchmark receipts",
        final_model_gate="Bedrock GPT-5.4 xhigh when changing wrapper behavior; 5.5 only for production rollout decision",
        live_authority="deploy/restart needs approval or guarded rollout command",
        hybridization="deterministic log parser plus cheap classifier; frontier only for policy-changing patch review",
        benchmark_cases_to_add=(
            "empty provider completion",
            "progress-only turn",
            "oversized uncompressed context",
            "sticky direct OpenAI service tier on work-special",
        ),
        notes="This is a high-savings area because most evidence is logs and counters.",
    ),
    RunbookPattern(
        pattern_id="work_special_model_lane_rollout",
        label="Work-special model lane rollout and verification",
        domain="model-routing",
        family="deployment",
        owner_tui="control-plane",
        tenant_boundary="OpenBrand work-provisioned TUIs only",
        keywords=(
            "work-special",
            "bedrock codex",
            "selected_runtime",
            "selected_model",
            "default_service_tier",
            "all 12",
            "sync_agent_console_template",
            "model picker",
            "claude",
            "kimi",
        ),
        min_keyword_hits=2,
        runbook_outputs=(
            "work-special-model-lane-rollout",
            "model-picker-verification",
        ),
        skill_outputs=("work-tui-model-routing",),
        tool_outputs=(
            "scripts/sync_agent_console_template.py",
            "scripts/tui_auto_mode_benchmark.py",
            "scripts/tui_capability_inventory.py",
        ),
        deterministic_validators=(
            "selected_runtime",
            "selected_model",
            "default_service_tier",
            "ui_version",
        ),
        lower_model_role="read inventory and draft rollout diff",
        final_model_gate="Bedrock GPT-5.4 xhigh for rollout plan; operator approval before deploy/restart",
        live_authority="deployment and provider spending changes are approval-gated",
        hybridization="local inventory -> cheap diff summarizer -> 5.4 rollout verifier",
        benchmark_cases_to_add=(
            "work TUI should default to Bedrock",
            "personal TUI should avoid work purse",
            "sticky browser preference conflicts with fleet default",
            "Kimi/Claude lane present but not default",
        ),
        notes="Should become a first-class tenant/purse policy runbook, not host-name folklore.",
    ),
    RunbookPattern(
        pattern_id="runbook_contract_pack_audit",
        label="Runbook contract-pack audit and hybrid architecture",
        domain="runbook-governance",
        family="governance",
        owner_tui="control-plane",
        tenant_boundary="work runbooks stay in OpenBrand tenant",
        keywords=(
            "runbook contract",
            "authority gates",
            "allowed_reads",
            "blocked_worker_actions",
            "hybrid architecture",
            "confluence mirror",
            "runbook routing matrix",
            "runbook qa",
        ),
        min_keyword_hits=2,
        runbook_outputs=("runbook-contract-pack", "runbook-hybrid-audit"),
        skill_outputs=("runbook-pack-authoring",),
        tool_outputs=(
            "scripts/runbook_contract_pack_audit.py",
            "scripts/runbook_hybrid_architecture_audit.py",
        ),
        deterministic_validators=(
            "authority_gates present",
            "allowed_reads present",
            "blocked_worker_actions present",
            "tests documented",
        ),
        lower_model_role="extract evidence/action/authority fields from runbook text",
        final_model_gate="Bedrock GPT-5.4 xhigh for tiering and authority interpretation",
        live_authority="no live action; governance changes require review",
        hybridization="cheap extraction with deterministic schema audit; 5.4 adjudicates risk tier",
        benchmark_cases_to_add=(
            "missing authority gate",
            "unclear allowed write",
            "runbook with local-only evidence",
            "runbook requiring human approval",
        ),
        notes="This is the bridge from old session knowledge into reusable skills.",
    ),
    RunbookPattern(
        pattern_id="gaphelp_helpdesk_runbook_routing",
        label="GAPHELP/helpdesk ticket runbook routing",
        domain="helpdesk",
        family="runbook",
        owner_tui="control-plane/phone-ops",
        tenant_boundary="ticket tenant and owner must match execution surface",
        keywords=(
            "gaphelp",
            "help desk",
            "help-desk",
            "ticket",
            "runbook selection",
            "resolution precision",
            "same runbook",
            "oracle",
            "approval stop",
        ),
        min_keyword_hits=2,
        runbook_outputs=("helpdesk-runbook-routing", "safe-close-verifier"),
        skill_outputs=("ticket-runbook-triage",),
        tool_outputs=("scripts/gaphelp_ticket_loop_shadow.py",),
        deterministic_validators=(
            "expected_runbook",
            "forbidden terms absent",
            "approval gate respected",
            "required evidence terms present",
        ),
        lower_model_role="classify ticket, retrieve evidence, draft safe non-mutating resolution",
        final_model_gate="Bedrock GPT-5.4 xhigh for multi-source root cause; 5.5 for high-authority close",
        live_authority="Jira/helpdesk writes and closeouts approval-gated until live canaries pass",
        hybridization="local prefilter -> cheap selector -> 5.4 verifier -> rare 5.5 final",
        benchmark_cases_to_add=(
            "ambiguous ticket abstain",
            "approval-only product data request",
            "wrong-owner tenant mismatch",
            "safe close with complete evidence",
        ),
        notes="Already has the strongest benchmark coverage; next step is labeled real ticket samples.",
    ),
    RunbookPattern(
        pattern_id="goldbook_attribute_validator_category",
        label="Gold Book attribute fill, validators, and category governance",
        domain="gold-book",
        family="data-governance",
        owner_tui="gold-book",
        tenant_boundary="OpenBrand work data only",
        keywords=(
            "gold book",
            "goldbook",
            "SpecMaster",
            "writespecs",
            "attribute fill",
            "validation builder",
            "validator",
            "category creation",
            "category governance",
        ),
        min_keyword_hits=2,
        runbook_outputs=(
            "goldbook-attribute-fill",
            "goldbook-validator-builder",
            "goldbook-category-creation",
            "writespecs-dry-run-repair",
        ),
        skill_outputs=("goldbook-workflow",),
        tool_outputs=(
            "scripts/work_loop_canary.py",
            "scripts/work_domain_skill_benchmark.py",
        ),
        deterministic_validators=(
            "source evidence citation",
            "fixture diff",
            "pytest",
            "writespecs dry run",
            "duplicate category search",
        ),
        lower_model_role="source lookup, simple enum fill, fixture generation, dry-run repair draft",
        final_model_gate="Bedrock GPT-5.4 xhigh for conflicts/category governance; 5.5 for release/final decision",
        live_authority="live SpecMaster writes and category release need work-special owner approval",
        hybridization="cheap retrieval/code workers under deterministic validators; 5.4 handles adjudication",
        benchmark_cases_to_add=(
            "clear evidence attribute fill",
            "conflicting merchant/PDF evidence",
            "required-field validator",
            "category dedupe/merge guard",
        ),
        notes="Large portions are lower-model friendly when validators are mandatory.",
    ),
    RunbookPattern(
        pattern_id="webgoat_selector_jmespath_merchant",
        label="WebGOAT selectors, JMESPath extraction, and merchant onboarding",
        domain="webgoat",
        family="code-data",
        owner_tui="control-plane",
        tenant_boundary="OpenBrand work data only; auth artifacts must not be printed",
        keywords=(
            "webgoat",
            "xpath",
            "jmespath",
            "merchant",
            "selector",
            "parser",
            "scraper",
            "category mapping",
            "auth artifact",
        ),
        min_keyword_hits=2,
        runbook_outputs=(
            "webgoat-selector-builder",
            "webgoat-jmespath-extraction",
            "merchant-onboarding",
            "scraper-release-gate",
        ),
        skill_outputs=("webgoat-parser-repair",),
        tool_outputs=("webgoat_oneoff_probe", "Playwright", "pytest", "snapshot diff"),
        deterministic_validators=(
            "selector fixture",
            "JMESPath validator",
            "snapshot diff",
            "schema validator",
            "auth file presence only",
        ),
        lower_model_role="bounded selector/JMESPath draft, parser fixture generation, snapshot diff summary",
        final_model_gate="Bedrock GPT-5.4 xhigh for resilient selectors/merchant governance; 5.5 for live governance close",
        live_authority="live merchant registry/parser changes approval-gated",
        hybridization="cheap code workers plus deterministic browser/parser tests; 5.4 validates brittle layout decisions",
        benchmark_cases_to_add=(
            "simple XPath price field",
            "resilient XPath with sponsored block",
            "nested JMESPath offers extraction",
            "merchant canonicalization duplicate",
        ),
        notes="Good place to spend on tests rather than frontier tokens.",
    ),
    RunbookPattern(
        pattern_id="bbs_handoff_lifecycle",
        label="BBS handoff lifecycle and close-loop discipline",
        domain="bbs",
        family="coordination",
        owner_tui="switchboard/control-plane",
        tenant_boundary="cross-tenant coordination, but no ownership ACK unless taking over",
        keywords=(
            "BBS",
            "handoff",
            "ACK",
            "fork",
            "blocked",
            "unacked",
            "bbs_task_lifecycle",
        ),
        min_keyword_hits=2,
        runbook_outputs=("bbs-handoff-close-loop", "bbs-owner-ack-policy"),
        skill_outputs=("bbs-coordination",),
        tool_outputs=(
            "scripts/bbs_task_lifecycle.py",
            "scripts/bbs_doctor.py",
            "scripts/bbs_janitor.py",
        ),
        deterministic_validators=(
            "actor/owner match",
            "ack note present",
            "blocked reason present",
            "done reason present",
        ),
        lower_model_role="summarize state and propose close-loop action",
        final_model_gate="Bedrock GPT-5.4 xhigh only for ambiguous ownership or cross-boundary escalation",
        live_authority="ACK/fork/done/blocked writes require explicit role decision",
        hybridization="local ledger parser; cheap model drafts coordination note; 5.4 checks authority",
        benchmark_cases_to_add=(
            "observer must not ACK",
            "owner ACK allowed",
            "coordinator fork allowed",
            "blocked requires concrete blocker",
        ),
        notes="This is mostly policy and ledger validation; lower models can draft but not execute writes blindly.",
    ),
    RunbookPattern(
        pattern_id="context_token_optimizer",
        label="Context, token, and spend optimizer",
        domain="cost-control",
        family="optimization",
        owner_tui="control-plane",
        tenant_boundary="billing owner and tenant must be explicit",
        keywords=(
            "token spend",
            "context optimizer",
            "compact context",
            "ticket_token_cost_ledger",
            "cost",
            "flex",
            "batch",
            "bedrock pricing",
            "model matrix",
        ),
        min_keyword_hits=2,
        runbook_outputs=("context-budget-pack", "model-cost-ledger"),
        skill_outputs=("cost-aware-routing",),
        tool_outputs=(
            "scripts/ticket_token_cost_ledger.py",
            "scripts/tui_context_replay_benchmark.py",
            "scripts/work_domain_skill_benchmark.py",
        ),
        deterministic_validators=(
            "rate card source",
            "token shape",
            "cost baseline",
            "invoice reconciliation status",
        ),
        lower_model_role="summarize ledgers, compute deltas, flag expensive unchanged context",
        final_model_gate="Bedrock GPT-5.4 xhigh for policy changes; no 5.5 unless approving spend/deploy",
        live_authority="purse-affecting defaults require explicit approval",
        hybridization="deterministic accounting first; cheap summarizer; 5.4 for policy routing",
        benchmark_cases_to_add=(
            "unchanged ticket replay skipped",
            "cached-input estimate",
            "Bedrock vs direct pricing label",
            "OpenAI fast baseline percentage",
        ),
        notes="A lot of value is in better measurement and caching, not a smarter final model.",
    ),
    RunbookPattern(
        pattern_id="work_special_tool_baseline",
        label="Work-special operator tool baseline",
        domain="tui-ops",
        family="tooling",
        owner_tui="control-plane/infra",
        tenant_boundary="OpenBrand work host only",
        keywords=(
            "missing basic tools",
            "sqlite3",
            "uv",
            "pnpm",
            "yarn",
            "corepack",
            "operator cli",
            "tool baseline",
        ),
        min_keyword_hits=2,
        runbook_outputs=("work-special-tool-baseline",),
        skill_outputs=("work-host-tooling-check",),
        tool_outputs=("scripts/tui_capability_inventory.py",),
        deterministic_validators=("command -v", "version check", "package inventory"),
        lower_model_role="read inventory and produce missing-tool list",
        final_model_gate="local deterministic unless package install plan is broad",
        live_authority="package install requires operator approval or predefined baseline",
        hybridization="no LLM needed for checks; cheap model can explain diff",
        benchmark_cases_to_add=(
            "sqlite3 missing",
            "uv installed but uvx missing",
            "pytest absent from venv",
        ),
        notes="Should be mostly deterministic and very cheap.",
    ),
    RunbookPattern(
        pattern_id="dns_caddy_frontdoor_persistence",
        label="DNS/Caddy/frontdoor alias persistence",
        domain="netops",
        family="infrastructure",
        owner_tui="netops",
        tenant_boundary="target tenant depends on hostname; root lane only for host changes",
        keywords=(
            "Caddy",
            "DNS",
            "DOHIO",
            "alias",
            "frontdoor",
            "forced-DNS",
            "dig +short",
            "root-owned",
            "NetOps/root",
        ),
        min_keyword_hits=2,
        runbook_outputs=("dns-caddy-alias-persistence", "frontdoor-validation"),
        skill_outputs=("netops-frontdoor-change",),
        tool_outputs=(
            "scripts/render_norman_bot_proxy_caddy.py",
            "scripts/apply_norman_bot_proxy_live.py",
        ),
        deterministic_validators=(
            "caddy adapt",
            "dig expected A record",
            "curl host check",
            "backup snapshot",
        ),
        lower_model_role="prepare diff, validation checklist, and rollback note",
        final_model_gate="Bedrock GPT-5.4 xhigh for root-side plan; human approval before mutation",
        live_authority="root/DNS/Caddy writes require NetOps/root authority",
        hybridization="deterministic renderer/validator; LLM drafts plan and checks missing validation",
        benchmark_cases_to_add=(
            "runtime Caddy route live but DNS missing",
            "split-DNS alias persistence",
            "root-owned file blocks unprivileged lane",
        ),
        notes="Good repeatable runbook; risky only at the final write boundary.",
    ),
    RunbookPattern(
        pattern_id="bedrock_marketplace_access",
        label="Bedrock marketplace/model access and AWS support evidence",
        domain="model-routing",
        family="access",
        owner_tui="control-plane/infra",
        tenant_boundary="OpenBrand AWS accounts only",
        keywords=(
            "AWS Support",
            "marketplace",
            "model access",
            "ob-openbrand-admin",
            "ob-traqline-admin",
            "Bedrock access",
            "support case",
            "subscribe",
        ),
        min_keyword_hits=1,
        runbook_outputs=("bedrock-model-access-check", "aws-support-evidence-pack"),
        skill_outputs=("bedrock-access-triage",),
        tool_outputs=(
            "aws bedrock list-foundation-models",
            "aws support describe-cases",
        ),
        deterministic_validators=(
            "aws sts get-caller-identity",
            "model list contains expected id",
            "support case read/write auth status",
        ),
        lower_model_role="summarize model availability and blocked account/profile state",
        final_model_gate="Bedrock GPT-5.4 xhigh for access recommendation; human approval before support/marketplace spend",
        live_authority="marketplace subscription and support updates are approval-gated",
        hybridization="AWS CLI facts first; cheap model explains; 5.4 for procurement recommendation",
        benchmark_cases_to_add=(
            "profile has STS but no support permission",
            "model unavailable in region",
            "subscription approved but model call blocked",
        ),
        notes="Do not let the model infer access from docs; require live account evidence.",
    ),
    RunbookPattern(
        pattern_id="control_plane_always_on_loop",
        label="Control-plane always-on loop, canary, and sentinel operation",
        domain="control-plane",
        family="runbook",
        owner_tui="control-plane",
        tenant_boundary="work-special only for OpenBrand work systems; personal TUIs stay separately labeled",
        keywords=(
            "control plane",
            "control-plane",
            "control panel",
            "cp.kris",
            "always-on",
            "work_loop_canary",
            "sentinel",
            "queue depth",
            "safe action",
            "HAL",
        ),
        min_keyword_hits=2,
        runbook_outputs=(
            "control-plane-loop-canary",
            "control-plane-safe-action-ladder",
            "control-plane-sentinel-health",
        ),
        skill_outputs=("control-plane-loop-operator",),
        tool_outputs=(
            "scripts/work_loop_canary.py",
            "scripts/tui_fleet_doctor.py",
            "scripts/work_domain_skill_benchmark.py",
        ),
        deterministic_validators=(
            "loop iteration receipt",
            "queue depth before/after",
            "no live writes in shadow",
            "BBS/task state receipt",
            "fleet doctor receipt",
        ),
        lower_model_role="watch queue/fleet snapshots, classify simple loop actions, draft safe next-step notes",
        final_model_gate="Bedrock GPT-5.4 xhigh for cross-system action plans; Bedrock GPT-5.5 xhigh only for irreversible/high-authority close",
        live_authority="live task closure, route changes, deploy/restart, and purse changes require explicit authority",
        hybridization="deterministic watchers and canaries first; cheap worker summarizes; 5.4 adjudicates; 5.5 only at final high-authority gate",
        benchmark_cases_to_add=(
            "queue item needs local-only refresh",
            "ambiguous owner/tenant boundary",
            "fleet wedge with no live writes allowed",
            "safe action ladder escalates to approval",
        ),
        notes="This is the main place to encode better/cheaper/faster/safe behavior as policy plus receipts.",
    ),
    RunbookPattern(
        pattern_id="tui_operator_common_workflows",
        label="Common TUI operator workflows: status, plan, undo, queue, and handoff",
        domain="tui-ops",
        family="operator-workflow",
        owner_tui="all TUIs; work-special owns OpenBrand work execution",
        tenant_boundary="work-special and personal TUIs must stay explicitly labeled before action",
        keywords=(
            "working on",
            "turn_plan",
            "status action",
            "ask status",
            "operator status",
            "plan estimate",
            "cost estimate",
            "undo",
            "unwind",
            "remove queued",
            "interrupt queued",
            "recover staged prompt",
            "BBS close-loop",
            "tenant boundary",
            "purse",
        ),
        min_keyword_hits=2,
        runbook_outputs=(
            "tui-operator-status-answer",
            "tui-working-on-plan-estimate",
            "tui-safe-undo-unwind-gate",
            "tui-queue-interrupt-recovery",
            "tui-tenant-purse-route-check",
        ),
        skill_outputs=("tui-operator-workflow-skills",),
        tool_outputs=(
            "/api/status",
            "/api/unwind",
            "queued prompt controls",
            "scripts/bbs_task_lifecycle.py",
            "scripts/gaphelp_ticket_loop_shadow.py",
        ),
        deterministic_validators=(
            "status snapshot present",
            "turn_plan estimate logged",
            "queue depth before/after",
            "latest-turn boundary checked",
            "tenant/purse label present",
            "approval stop recorded for state change",
        ),
        lower_model_role="summarize status, draft plan/cost estimates, retrieve context, and propose wait/remove/interrupt choices",
        final_model_gate="Bedrock GPT-5.4 xhigh for undo, BBS writes, tenant/purse routing, or any state-changing recommendation",
        live_authority="unwind, queue mutation, BBS writes, route defaults, and external rollback remain explicit operator actions",
        hybridization="local snapshot first; cheap Bedrock worker narrates or drafts; 5.4 checks authority before mutation",
        benchmark_cases_to_add=(
            "operator asks what are you working on",
            "queued prompt should wait rather than interrupt",
            "latest local turn can be unwound but external write cannot",
            "work-special/personal tenant mismatch blocks execution",
        ),
        notes="These workflows are common across every TUI and should be first-class skills, not hidden UI habits.",
    ),
    RunbookPattern(
        pattern_id="session_runbook_promotion",
        label="Old session mining into repeatable runbooks, skills, and tools",
        domain="runbook-governance",
        family="governance",
        owner_tui="control-plane",
        tenant_boundary="work-special evidence stays OpenBrand; personal-session evidence remains labeled personal",
        keywords=(
            "old sessions",
            "session miner",
            "work sessions",
            "repeatable runbooks",
            "skills",
            "tools",
            "foundational skills",
            "benchmark matrix",
            "hybridized",
        ),
        min_keyword_hits=2,
        runbook_outputs=(
            "session-to-runbook-promotion",
            "skill-candidate-generator",
            "tool-gap-inventory",
        ),
        skill_outputs=("session-runbook-mining",),
        tool_outputs=("scripts/work_session_runbook_miner.py",),
        deterministic_validators=(
            "redaction pass",
            "source path retained",
            "candidate manifest",
            "positive/ambiguous/forbidden benchmark cases",
        ),
        lower_model_role="extract repeated workflow fields, draft skill skeletons, identify missing validators",
        final_model_gate="Bedrock GPT-5.4 xhigh for promotion/risk tier; 5.5 only for broad production policy changes",
        live_authority="no live action from mined history; promotion to production requires review",
        hybridization="cheap extraction from redacted history; deterministic schema checks; 5.4 reviews risk and tenant boundary",
        benchmark_cases_to_add=(
            "session contains secret-like text",
            "work-special evidence separated from personal evidence",
            "candidate missing validator is not promoted",
            "same workflow appears across three sessions",
        ),
        notes="This closes the loop from one-off work into reusable Norman capabilities.",
    ),
)


def _redact(text: str) -> str:
    redacted = text
    for pattern, replacement in REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _strip_prompt_boilerplate(text: str) -> str:
    markers = (
        "\nGovernance drift preflight:",
        "\nBBS handoff notice",
        "\nContext preflight:",
        "\nWhen you respond",
        "\n<environment_context>",
    )
    cut = len(text)
    for marker in markers:
        idx = text.find(marker)
        if idx >= 0:
            cut = min(cut, idx)
    return text[:cut]


def _preview(text: str, limit: int = 220) -> str:
    clean = " ".join(_redact(text).split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "..."


def _cap_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 80] + "\n[TRUNCATED_FOR_MINING]\n" + text[-40:]


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_timestamp(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_loads(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _content_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_content_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "message", "output", "arguments", "name"):
            if key in value and isinstance(value[key], str):
                return str(value[key])
        parts = [_content_text(item) for item in value.values()]
        return "\n".join(part for part in parts if part)
    return str(value)


def _is_session_boilerplate(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return stripped.startswith(
        (
            "# AGENTS.md instructions",
            "<environment_context>",
            "<permissions instructions>",
            "You are Codex,",
            "# Collaboration Mode:",
        )
    )


def _clean_session_user_text(text: str) -> str:
    clean = _strip_prompt_boilerplate(text).strip()
    if _is_session_boilerplate(clean):
        return ""
    return clean


def _turn_from_payload(
    payload: dict[str, Any], *, source_path: Path, fallback_id: str
) -> SessionTurn:
    return SessionTurn(
        turn_id=str(payload.get("id") or fallback_id),
        source_path=str(source_path),
        thread_id=str(payload.get("thread_id") or ""),
        started_at=_coerce_int(payload.get("started_at")),
        model=str(payload.get("model") or ""),
        service_tier=str(payload.get("service_tier") or payload.get("speed") or ""),
        prompt=str(payload.get("prompt") or payload.get("prompt_preview") or ""),
        response=str(payload.get("response") or payload.get("response_preview") or ""),
    )


def load_sqlite_turns(path: Path) -> list[SessionTurn]:
    if not path.exists():
        return []
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            ).fetchall()
        }
        if "turns" not in tables:
            return []
        rows = conn.execute(
            """
            SELECT id, thread_id, started_at, model, service_tier,
                   prompt_preview, response_preview, payload_json
            FROM turns
            ORDER BY started_at
            """
        ).fetchall()
    finally:
        conn.close()
    turns: list[SessionTurn] = []
    for row in rows:
        payload = _json_loads(str(row["payload_json"] or ""))
        fallback = {
            "id": str(row["id"] or ""),
            "thread_id": str(row["thread_id"] or ""),
            "started_at": _coerce_int(row["started_at"]),
            "model": str(row["model"] or ""),
            "service_tier": str(row["service_tier"] or ""),
            "prompt": str(row["prompt_preview"] or ""),
            "response": str(row["response_preview"] or ""),
        }
        payload = {**fallback, **payload}
        turns.append(
            _turn_from_payload(payload, source_path=path, fallback_id=fallback["id"])
        )
    return turns


def load_history_turns(path: Path) -> list[SessionTurn]:
    if not path.exists():
        return []
    turns: list[SessionTurn] = []
    for index, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = line.strip()
        if not stripped:
            continue
        payload = _json_loads(stripped)
        if not payload:
            continue
        fallback_id = _digest(f"{path}:{index}:{stripped[:512]}")
        turns.append(
            _turn_from_payload(payload, source_path=path, fallback_id=fallback_id)
        )
    return turns


def load_session_turns(path: Path) -> list[SessionTurn]:
    """Load a Codex session JSONL as one mined record.

    Session logs interleave user messages, assistant messages, tool calls, and tool
    outputs. For runbook mining we want evidence that a repeated workflow existed,
    not a perfect conversational reconstruction, so one bounded aggregate per
    session keeps the miner deterministic and avoids emitting raw transcripts.
    """
    if not path.exists():
        return []

    session_id = ""
    started_at = 0
    thread_id = ""
    model = ""
    service_tier = ""
    user_parts: list[str] = []
    response_parts: list[str] = []

    for index, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        payload = _json_loads(line.strip())
        if not payload:
            continue
        event_ts = _coerce_timestamp(payload.get("timestamp"))
        if event_ts and (not started_at or event_ts < started_at):
            started_at = event_ts

        event_type = str(payload.get("type") or "")
        body = payload.get("payload")
        if not isinstance(body, dict):
            continue

        if event_type == "session_meta":
            session_id = str(body.get("id") or session_id)
            started_at = _coerce_timestamp(body.get("timestamp")) or started_at
            model = str(body.get("model") or body.get("model_slug") or model)
            continue

        if event_type == "turn_context":
            thread_id = str(body.get("turn_id") or thread_id)
            model = str(body.get("model") or model)
            service_tier = str(body.get("service_tier") or service_tier)
            continue

        body_type = str(body.get("type") or "")
        if event_type == "event_msg" and body_type == "task_started":
            thread_id = str(body.get("turn_id") or thread_id)
            continue

        if event_type == "event_msg" and body_type == "user_message":
            text = _clean_session_user_text(str(body.get("message") or ""))
            if text:
                user_parts.append(text)
            continue

        if event_type != "response_item":
            continue

        if body_type == "message":
            role = str(body.get("role") or "")
            text = _content_text(body.get("content")).strip()
            if role == "user":
                text = _clean_session_user_text(text)
                if text:
                    user_parts.append(text)
            elif role == "assistant":
                if text:
                    response_parts.append(text)
            continue

        if body_type == "function_call":
            name = str(body.get("name") or "")
            args = _content_text(body.get("arguments")).strip()
            if name:
                response_parts.append(f"tool_call: {name}\n{args}".strip())
            continue

        if body_type == "function_call_output":
            output = _content_text(body.get("output")).strip()
            if output:
                response_parts.append(output)

    prompt = _cap_text("\n\n".join(user_parts), MAX_SESSION_PROMPT_CHARS)
    response = _cap_text("\n\n".join(response_parts), MAX_SESSION_RESPONSE_CHARS)
    if not prompt and not response:
        return []

    fallback_id = _digest(f"{path}:{started_at}:{prompt[:512]}:{response[:512]}")
    return [
        SessionTurn(
            turn_id=session_id or fallback_id,
            source_path=str(path),
            thread_id=thread_id or session_id,
            started_at=started_at,
            model=model,
            service_tier=service_tier,
            prompt=prompt,
            response=response,
        )
    ]


def discover_sources(roots: list[Path]) -> tuple[list[Path], list[Path], list[Path]]:
    sqlite_paths: list[Path] = []
    history_paths: list[Path] = []
    session_paths: list[Path] = []
    for root in roots:
        if root.is_file():
            paths = [root]
        elif root.is_dir():
            paths = list(root.rglob("history.jsonl"))
            paths.extend(root.rglob("tui_state.sqlite3"))
            paths.extend(
                path for path in root.rglob("*.jsonl") if "sessions" in path.parts
            )
        else:
            continue
        for path in paths:
            if path.name == "tui_state.sqlite3":
                sqlite_paths.append(path)
            elif path.name == "history.jsonl":
                history_paths.append(path)
            elif path.suffix == ".jsonl" and "sessions" in path.parts:
                session_paths.append(path)
    return (
        sorted(set(sqlite_paths)),
        sorted(set(history_paths)),
        sorted(set(session_paths)),
    )


def load_turns(
    sqlite_paths: list[Path],
    history_paths: list[Path],
    session_paths: list[Path] | None = None,
) -> list[SessionTurn]:
    by_key: dict[str, SessionTurn] = {}
    for path in sqlite_paths:
        for turn in load_sqlite_turns(path):
            key = _turn_key(turn)
            by_key[key] = turn
    for path in history_paths:
        for turn in load_history_turns(path):
            key = _turn_key(turn)
            existing = by_key.get(key)
            if existing is None or _text_len(turn) > _text_len(existing):
                by_key[key] = turn
    for path in session_paths or []:
        for turn in load_session_turns(path):
            key = _turn_key(turn)
            existing = by_key.get(key)
            if existing is None or _text_len(turn) > _text_len(existing):
                by_key[key] = turn
    return sorted(by_key.values(), key=lambda turn: (turn.started_at, turn.turn_id))


def _text_len(turn: SessionTurn) -> int:
    return len(turn.prompt) + len(turn.response)


def _turn_key(turn: SessionTurn) -> str:
    material = json.dumps(
        {
            "thread_id": turn.thread_id,
            "started_at": turn.started_at,
            "prompt": _strip_prompt_boilerplate(turn.prompt)[:1024],
            "response": turn.response[:1024],
        },
        sort_keys=True,
    )
    if turn.prompt or turn.response:
        return _digest(material)
    return turn.turn_id or _digest(f"{turn.source_path}:{turn.started_at}")


def _keyword_hits(pattern: RunbookPattern, text: str) -> list[str]:
    lower = text.lower()
    if pattern.pattern_id == "bbs_handoff_lifecycle" and not any(
        term in lower
        for term in (
            "bbs handoff",
            "unacked",
            "bbs_task_lifecycle",
            "owner ack",
            "coordinator",
            "fork helper",
            "blocked helper",
            "done helper",
        )
    ):
        return []
    return [keyword for keyword in pattern.keywords if keyword.lower() in lower]


def _iso(ts: int) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _score_candidate(
    pattern: RunbookPattern, evidence_count: int, thread_count: int
) -> dict[str, Any]:
    has_validator = bool(pattern.deterministic_validators)
    high_authority = any(
        term in pattern.live_authority.lower()
        for term in ("approval", "root", "write", "subscription", "restart", "deploy")
    )
    repeatability = min(
        1.0,
        0.18
        + min(evidence_count, 8) * 0.07
        + min(thread_count, 4) * 0.08
        + (0.12 if pattern.tool_outputs else 0.0)
        + (0.10 if pattern.runbook_outputs else 0.0)
        + (0.08 if pattern.skill_outputs else 0.0),
    )
    automation_safety = min(
        1.0,
        max(
            0.0,
            0.58
            + (0.22 if has_validator else -0.08)
            + (0.08 if "local" in pattern.hybridization.lower() else 0.0)
            - (0.18 if high_authority else 0.0),
        ),
    )
    hybrid_value = min(
        1.0,
        0.30
        + min(evidence_count, 6) * 0.06
        + (0.18 if pattern.lower_model_role else 0.0)
        + (0.14 if has_validator else 0.0)
        + (0.08 if "cheap" in pattern.hybridization.lower() else 0.0),
    )
    if not has_validator or evidence_count < 2:
        comfort = "needs_more_cases_or_validator"
    elif high_authority:
        comfort = "worker_only_until_gate"
    elif automation_safety >= 0.76 and hybrid_value >= 0.66:
        comfort = "comfortable_shadow_lower_worker"
    else:
        comfort = "needs_more_cases_or_validator"
    return {
        "repeatability_score": round(repeatability, 3),
        "automation_safety_score": round(automation_safety, 3),
        "hybrid_value_score": round(hybrid_value, 3),
        "comfort": comfort,
    }


def _recommendation(pattern: RunbookPattern, scores: dict[str, Any]) -> str:
    comfort = str(scores["comfort"])
    if comfort == "comfortable_shadow_lower_worker":
        return "Promote to runbook/skill candidate with lower-model worker canaries."
    if comfort == "worker_only_until_gate":
        return "Use lower models before the authority gate; keep final mutation gated."
    return "Add benchmark cases and deterministic validators before relying on lower models."


def build_report(
    turns: list[SessionTurn],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rows: list[dict[str, Any]] = []
    unmatched_relevant = 0
    matched_turn_ids: set[str] = set()
    for pattern in RUNBOOK_PATTERNS:
        matches: list[dict[str, Any]] = []
        for turn in turns:
            prompt = _strip_prompt_boilerplate(turn.prompt)
            combined = f"{prompt}\n{turn.response}"
            hits = _keyword_hits(pattern, combined)
            if len(hits) < pattern.min_keyword_hits:
                continue
            matched_turn_ids.add(turn.turn_id)
            matches.append(
                {
                    "turn_id": turn.turn_id,
                    "thread_id": turn.thread_id,
                    "source_path": turn.source_path,
                    "started_at": _iso(turn.started_at),
                    "model": turn.model,
                    "service_tier": turn.service_tier,
                    "keyword_hits": hits,
                    "prompt_preview": _preview(prompt),
                    "response_preview": _preview(turn.response),
                }
            )
        if not matches:
            continue
        thread_count = len(
            {str(match["thread_id"]) for match in matches if match["thread_id"]}
        )
        scores = _score_candidate(pattern, len(matches), thread_count)
        rows.append(
            {
                **asdict(pattern),
                "evidence_turn_count": len(matches),
                "thread_count": thread_count,
                "first_seen": matches[0]["started_at"],
                "last_seen": matches[-1]["started_at"],
                "scores": scores,
                "recommendation": _recommendation(pattern, scores),
                "evidence_samples": matches[-4:],
            }
        )

    relevant_terms = (
        "work-special",
        "work sessions",
        "runbook",
        "gold",
        "webgoat",
        "ticket",
        "wedge",
        "bedrock",
        "bbs",
        "control plane",
        "control panel",
    )
    for turn in turns:
        text = f"{_strip_prompt_boilerplate(turn.prompt)}\n{turn.response}".lower()
        if turn.turn_id not in matched_turn_ids and any(
            term in text for term in relevant_terms
        ):
            unmatched_relevant += 1

    summary_by_domain: dict[str, dict[str, Any]] = {}
    for row in rows:
        domain = str(row["domain"])
        item = summary_by_domain.setdefault(
            domain,
            {
                "candidate_count": 0,
                "evidence_turn_count": 0,
                "comfortable_shadow_lower_worker_count": 0,
                "worker_only_until_gate_count": 0,
                "needs_more_cases_or_validator_count": 0,
            },
        )
        item["candidate_count"] += 1
        item["evidence_turn_count"] += int(row["evidence_turn_count"])
        comfort = str(row["scores"]["comfort"])
        item[f"{comfort}_count"] += 1

    rows.sort(
        key=lambda row: (
            -float(row["scores"]["repeatability_score"]),
            -int(row["evidence_turn_count"]),
            str(row["pattern_id"]),
        )
    )
    comfortable_count = sum(
        1
        for row in rows
        if row["scores"]["comfort"] == "comfortable_shadow_lower_worker"
    )
    worker_gate_count = sum(
        1 for row in rows if row["scores"]["comfort"] == "worker_only_until_gate"
    )
    needs_count = sum(
        1 for row in rows if row["scores"]["comfort"] == "needs_more_cases_or_validator"
    )
    lower_worker_candidate_count = comfortable_count + worker_gate_count
    return {
        "schema": "norman.work-session-runbook-miner.v1",
        "generated_at": generated_at,
        "dry_run_only": True,
        "model_calls_executed": 0,
        "secret_policy": "history snippets are redacted and truncated; no raw secrets are emitted intentionally",
        "turn_count": len(turns),
        "candidate_count": len(rows),
        "summary": {
            "evidence_turn_count": sum(int(row["evidence_turn_count"]) for row in rows),
            "comfortable_shadow_lower_worker_count": comfortable_count,
            "worker_only_until_gate_count": worker_gate_count,
            "needs_more_cases_or_validator_count": needs_count,
            "lower_model_worker_candidate_count": lower_worker_candidate_count,
            "lower_model_worker_candidate_ratio": (
                round(lower_worker_candidate_count / len(rows), 3) if rows else 0.0
            ),
            "unmatched_relevant_turn_estimate": unmatched_relevant,
            "recommended_policy": (
                "Turn repeated sessions into small deterministic tools and concise skills. "
                "Use lower Bedrock workers for retrieval/data/code drafts, Bedrock GPT-5.4 "
                "xhigh for multi-source adjudication, and Bedrock GPT-5.5 xhigh only for "
                "rare final high-authority decisions."
            ),
        },
        "summary_by_domain": dict(sorted(summary_by_domain.items())),
        "rows": rows,
    }


def _cell(value: Any) -> str:
    return (
        str(value if value is not None else "").replace("\n", " ").replace("|", "\\|")
    )


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Work Session Runbook Miner",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Dry-run only: {report['dry_run_only']}; model calls executed: {report['model_calls_executed']}",
        f"- Turns scanned: {report['turn_count']}",
        f"- Candidate runbook/skill/tool patterns: {report['candidate_count']}",
        f"- Evidence-matching turns: {summary['evidence_turn_count']}",
        f"- Lower-model worker candidates, including gated workflows: {summary['lower_model_worker_candidate_count']} ({float(summary['lower_model_worker_candidate_ratio']) * 100:.1f}%)",
        f"- Comfortable lower-worker candidates: {summary['comfortable_shadow_lower_worker_count']}",
        f"- Worker-only-until-gate candidates: {summary['worker_only_until_gate_count']}",
        f"- Needs more cases/validator candidates: {summary['needs_more_cases_or_validator_count']}",
        "",
        "> This is mined from local TUI/session memory. It emits redacted snippets and should be treated as evidence for benchmark/runbook authoring, not proof that autonomous live execution is safe.",
        "",
        "## Domain Summary",
        "",
        "| Domain | Candidates | Evidence turns | Comfortable lower worker | Worker until gate | Needs more cases |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for domain, item in report["summary_by_domain"].items():
        lines.append(
            "| {domain} | {candidates} | {evidence} | {comfortable} | {gate} | {needs} |".format(
                domain=_cell(domain),
                candidates=item["candidate_count"],
                evidence=item["evidence_turn_count"],
                comfortable=item["comfortable_shadow_lower_worker_count"],
                gate=item["worker_only_until_gate_count"],
                needs=item["needs_more_cases_or_validator_count"],
            )
        )
    lines.extend(
        [
            "",
            "## Candidate Matrix",
            "",
            "| Candidate | Domain | Family | Evidence | Repeatability | Safety | Hybrid value | Comfort | Lower model role | Final gate | Outputs |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
        ]
    )
    for row in report["rows"]:
        scores = row["scores"]
        outputs = ", ".join(
            [
                *list(row["runbook_outputs"][:2]),
                *list(row["skill_outputs"][:1]),
                *list(row["tool_outputs"][:1]),
            ]
        )
        lines.append(
            "| {label} | {domain} | {family} | {evidence} | {repeat:.2f} | {safety:.2f} | {hybrid:.2f} | {comfort} | {lower} | {gate} | {outputs} |".format(
                label=_cell(row["label"]),
                domain=_cell(row["domain"]),
                family=_cell(row["family"]),
                evidence=row["evidence_turn_count"],
                repeat=float(scores["repeatability_score"]),
                safety=float(scores["automation_safety_score"]),
                hybrid=float(scores["hybrid_value_score"]),
                comfort=_cell(scores["comfort"]),
                lower=_cell(row["lower_model_role"]),
                gate=_cell(row["final_model_gate"]),
                outputs=_cell(outputs),
            )
        )
    lines.extend(["", "## Candidate Details", ""])
    for row in report["rows"]:
        scores = row["scores"]
        lines.extend(
            [
                f"### {_cell(row['label'])}",
                "",
                f"- Pattern id: `{row['pattern_id']}`",
                f"- Owner: `{row['owner_tui']}`; tenant boundary: {row['tenant_boundary']}",
                f"- Evidence: {row['evidence_turn_count']} turns across {row['thread_count']} thread(s), {row['first_seen']} to {row['last_seen']}",
                f"- Scores: repeatability {float(scores['repeatability_score']):.2f}, safety {float(scores['automation_safety_score']):.2f}, hybrid value {float(scores['hybrid_value_score']):.2f}",
                f"- Recommendation: {row['recommendation']}",
                f"- Hybrid split: {row['hybridization']}",
                f"- Live authority: {row['live_authority']}",
                f"- Deterministic validators: {', '.join(row['deterministic_validators'])}",
                f"- Runbook outputs: {', '.join(row['runbook_outputs'])}",
                f"- Skill outputs: {', '.join(row['skill_outputs'])}",
                f"- Tool outputs: {', '.join(row['tool_outputs'])}",
                f"- Benchmark cases to add: {', '.join(row['benchmark_cases_to_add'])}",
            ]
        )
        if row["evidence_samples"]:
            lines.append("- Recent redacted evidence samples:")
            for sample in row["evidence_samples"][-2:]:
                preview = sample["prompt_preview"] or sample["response_preview"]
                lines.append(
                    f"  - `{sample['started_at']}` hits={', '.join(sample['keyword_hits'][:5])}: {preview}"
                )
        lines.append("")
    lines.extend(
        [
            "## Interpretation",
            "",
            "- The repeated work-special patterns are not mostly frontier-reasoning problems. They are probe, parse, diff, validate, and gate problems.",
            "- Lower models look most useful as workers for retrieval, fixture generation, selector/JMESPath drafts, inventory summaries, runbook field extraction, and safe helpdesk drafts.",
            "- Bedrock GPT-5.4 xhigh is the right heavy-lift/default verifier for ambiguous multi-source decisions, tenant boundary checks, and live plan review.",
            "- Bedrock GPT-5.5 xhigh should stay rare: final high-authority close, release decisions, or operator-visible irreversible action decisions.",
            "- The next benchmark improvement is to convert each mined candidate into labeled cases with expected tool calls, expected runbook, allowed writes, forbidden writes, and validator receipts.",
        ]
    )
    return "\n".join(lines) + "\n"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "candidate"


def render_candidate_spec(row: dict[str, Any]) -> str:
    samples = row.get("evidence_samples") or []
    sample_lines = []
    for sample in samples[-3:]:
        sample_lines.append(
            "- `{started}` hits={hits}: {preview}".format(
                started=sample["started_at"],
                hits=", ".join(sample["keyword_hits"][:5]),
                preview=sample["prompt_preview"] or sample["response_preview"],
            )
        )
    if not sample_lines:
        sample_lines.append("- No redacted samples retained.")

    skill_name = _slug(
        str(row["skill_outputs"][0] if row["skill_outputs"] else row["pattern_id"])
    )
    return (
        "---\n"
        f"candidate_id: {row['pattern_id']}\n"
        f"domain: {row['domain']}\n"
        f"family: {row['family']}\n"
        f"owner_tui: {row['owner_tui']}\n"
        f"comfort: {row['scores']['comfort']}\n"
        "---\n\n"
        f"# {row['label']}\n\n"
        "## Purpose\n\n"
        f"Convert repeated session work into `{', '.join(row['runbook_outputs'])}` "
        f"with reusable skill/tool support.\n\n"
        "## Trigger\n\n"
        f"Use when the operator asks for work matching: {', '.join(row['keywords'])}.\n\n"
        "## Boundary\n\n"
        f"- Tenant/data boundary: {row['tenant_boundary']}\n"
        f"- Live authority: {row['live_authority']}\n"
        f"- Owner TUI: `{row['owner_tui']}`\n\n"
        "## Hybrid Model Split\n\n"
        f"- Lower-model role: {row['lower_model_role']}\n"
        f"- Final gate: {row['final_model_gate']}\n"
        f"- Hybridization pattern: {row['hybridization']}\n\n"
        "## Deterministic Tools And Validators\n\n"
        f"- Tools to wire: {', '.join(row['tool_outputs'])}\n"
        f"- Validators: {', '.join(row['deterministic_validators'])}\n\n"
        "## Skill Skeleton\n\n"
        "```yaml\n"
        f"name: {skill_name}\n"
        "description: Use when this repeated workflow appears; load only the "
        "specific runbook/tool references needed for the current tenant and authority boundary.\n"
        "```\n\n"
        "Keep `SKILL.md` concise. Put schemas, command examples, and long evidence "
        "examples in references or scripts.\n\n"
        "## Benchmark Cases To Add\n\n"
        + "\n".join(f"- {case}" for case in row["benchmark_cases_to_add"])
        + "\n\n"
        "## Mined Evidence\n\n"
        f"- Evidence turns: {row['evidence_turn_count']}\n"
        f"- Threads: {row['thread_count']}\n"
        f"- First seen: {row['first_seen']}\n"
        f"- Last seen: {row['last_seen']}\n"
        f"- Scores: repeatability={row['scores']['repeatability_score']}, "
        f"safety={row['scores']['automation_safety_score']}, "
        f"hybrid_value={row['scores']['hybrid_value_score']}\n\n"
        "Recent redacted samples:\n" + "\n".join(sample_lines) + "\n\n"
        "## Promotion Checklist\n\n"
        "- Add machine-readable runbook metadata: authority gates, allowed reads, "
        "allowed writes, blocked worker actions, owner, validator receipts.\n"
        "- Add at least one positive, one ambiguous, and one forbidden-action "
        "benchmark case.\n"
        "- Keep lower-model execution in shadow until validator receipts and live "
        "canaries match the stronger-model oracle.\n"
    )


def write_candidate_specs(report: dict[str, Any], output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for row in report["rows"]:
        path = output_dir / f"{_slug(str(row['pattern_id']))}.md"
        path.write_text(render_candidate_spec(row), encoding="utf-8")
        written.append(str(path))
    manifest = {
        "schema": "norman.work-session-runbook-candidate-manifest.v1",
        "generated_at": report["generated_at"],
        "candidate_count": len(written),
        "files": written,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    written.append(str(manifest_path))
    return written


def write_report(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    output_md.write_text(render_markdown(report), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mine local TUI/session history for repeatable work runbooks, skills, tools, and hybridization points."
    )
    parser.add_argument(
        "--sqlite",
        action="append",
        default=[],
        help="Path to a tui_state.sqlite3 file. May be repeated.",
    )
    parser.add_argument(
        "--history",
        action="append",
        default=[],
        help="Path to a history.jsonl file. May be repeated.",
    )
    parser.add_argument(
        "--session",
        action="append",
        default=[],
        help="Path to a Codex session JSONL file. May be repeated.",
    )
    parser.add_argument(
        "--discover-root",
        action="append",
        default=[],
        help=(
            "Directory or file to scan for history.jsonl, tui_state.sqlite3, and "
            "sessions/**/*.jsonl sources. May be repeated."
        ),
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument(
        "--output-candidates-dir",
        type=Path,
        default=None,
        help="Optional directory for per-pattern candidate runbook/skill/tool specs.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    discovered_sqlite, discovered_history, discovered_sessions = discover_sources(
        [Path(path).expanduser() for path in args.discover_root]
    )
    sqlite_paths = sorted(
        set([Path(path).expanduser() for path in args.sqlite] + discovered_sqlite)
    )
    history_paths = sorted(
        set([Path(path).expanduser() for path in args.history] + discovered_history)
    )
    session_paths = sorted(
        set([Path(path).expanduser() for path in args.session] + discovered_sessions)
    )
    turns = load_turns(sqlite_paths, history_paths, session_paths)
    report = build_report(turns)
    write_report(report, args.output_json, args.output_md)
    candidate_files = (
        write_candidate_specs(report, args.output_candidates_dir)
        if args.output_candidates_dir
        else []
    )
    print(
        json.dumps(
            {
                "candidate_files": len(candidate_files),
                "output_json": str(args.output_json),
                "output_md": str(args.output_md),
                "output_candidates_dir": str(args.output_candidates_dir or ""),
                "turn_count": report["turn_count"],
                "candidate_count": report["candidate_count"],
                "evidence_turn_count": report["summary"]["evidence_turn_count"],
                "history_files": len(history_paths),
                "session_files": len(session_paths),
                "sqlite_files": len(sqlite_paths),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
