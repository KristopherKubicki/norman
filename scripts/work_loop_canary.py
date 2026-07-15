#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.services.codex_role_policy import (
    codex_role_policy_identity,
    codex_role_value,
    load_codex_role_policy,
)
from app.services.norllama.route_policy import (
    route_policy_contract,
    route_policy_lifecycle,
)
from ticket_token_cost_ledger import (
    DEFAULT_LEDGER_JSONL as DEFAULT_TICKET_COST_LEDGER_JSONL,
)
from ticket_token_cost_ledger import append_record as append_ticket_cost_record
from ticket_token_cost_ledger import build_record as build_ticket_cost_record


CODEX_ROLE_POLICY = load_codex_role_policy()
CODEX_ROLE_POLICY_IDENTITY = codex_role_policy_identity(policy=CODEX_ROLE_POLICY)
EXPECTED_RUNTIME = "codex"
EXPECTED_MODEL = codex_role_value("work_standard", "model", policy=CODEX_ROLE_POLICY)
FINAL_AUTHORITY_MODEL = codex_role_value(
    "work_final_authority", "model", policy=CODEX_ROLE_POLICY
)
DEFAULT_MODE = "hybrid"

DEFAULT_OUTPUT_JSON = Path("/tmp/norman_tui_benchmarks/work_loop_canary.json")
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_benchmarks/work_loop_canary.md")
DEFAULT_OUTPUT_JOURNAL_JSON = Path(
    "/tmp/norman_tui_benchmarks/work_loop_canary_journal.json"
)
DEFAULT_SKILL_MATRIX_JSON = (
    Path("/tmp/norman_tui_benchmarks") / "work_domain_skill_matrix.json"
)
DEFAULT_FLOW_PLAN_JSON = Path("/tmp/norman_tui_benchmarks/tui_flow_canary_plan.json")
DEFAULT_FLOW_PLAN_MD = Path("/tmp/norman_tui_benchmarks/tui_flow_canary_plan.md")
DEFAULT_ROUTE_RECEIPT_DIR = Path("/var/lib/norman/route_receipts")
DEFAULT_CUTOVER_READINESS_JSON = Path(
    "/tmp/norman_tui_benchmarks/tui_cutover_readiness.json"
)
DEFAULT_CUTOVER_READINESS_MD = Path(
    "/tmp/norman_tui_benchmarks/tui_cutover_readiness.md"
)
DEFAULT_HISTORIC_ROUTE_BENCHMARK_JSON = Path(
    "/tmp/norman_tui_benchmarks/historic_shadow_planner_route_benchmark.json"
)
DEFAULT_ROUTE_RECEIPT_TEMPLATE_DIR = Path(
    "/tmp/norman_tui_benchmarks/route_receipt_templates"
)
DEFAULT_ROUTE_RECEIPT_MANIFEST_JSON = Path(
    "/tmp/norman_tui_benchmarks/tui_route_receipt_manifest.json"
)
DEFAULT_ROUTE_RECEIPT_MANIFEST_MD = Path(
    "/tmp/norman_tui_benchmarks/tui_route_receipt_manifest.md"
)
DEFAULT_ROUTE_RECEIPT_LAUNCH_JSON = Path(
    "/tmp/norman_tui_benchmarks/tui_route_receipt_launch_plan.json"
)
DEFAULT_ROUTE_RECEIPT_LAUNCH_MD = Path(
    "/tmp/norman_tui_benchmarks/tui_route_receipt_launch_plan.md"
)
DEFAULT_ROUTE_RECEIPT_HARVEST_JSON = Path(
    "/tmp/norman_tui_benchmarks/tui_route_receipt_harvest.json"
)
DEFAULT_ROUTE_RECEIPT_HARVEST_MD = Path(
    "/tmp/norman_tui_benchmarks/tui_route_receipt_harvest.md"
)

SAMPLE_INPUT_TOKENS = 100_000
SAMPLE_OUTPUT_TOKENS = 5_000
DEFAULT_FAST_LOOP_INTERVAL_SECONDS = 300
DEFAULT_MAX_CHANGED_TICKETS_PER_CYCLE = 3
DEFAULT_DAILY_BUDGET_USD = 10.0
MIN_CUTOVER_ROUTE_RECEIPTS = 50
MIN_CUTOVER_OBSERVATION_SECONDS = 24 * 60 * 60
MIN_CUTOVER_TASK_CLASS_QUOTA = 5
MIN_CUTOVER_TASK_CLASS_COUNT = 3
MIN_CUTOVER_VALIDATOR_PASS_RATE = 0.98
MAX_CUTOVER_MANUAL_OVERRIDE_RATE = 0.05
MAX_CUTOVER_FALLBACK_RATE = 0.15
MIN_CUTOVER_COST_SAVINGS = 0.25
MAX_CUTOVER_P95_LATENCY_MS = 120_000
RECEIPT_SIGNATURE_ALGORITHMS = {"hmac-sha256", "ed25519"}
MIN_HISTORIC_ROUTE_BENCHMARK_SAVINGS = 0.50
REQUIRED_HISTORIC_ROUTE_POLICY_VERSION = "work-special-hybrid-routing-policy.v1"
REQUIRED_HISTORIC_ROUTE_PLANNER_ACTION_POLICY_VERSION = "planner-action-contract.v1"
MIN_HISTORIC_ROUTE_PLANNER_ACTION_SCORE = 0.90
MAX_HISTORIC_ROUTE_BENCHMARK_FIVE_FIVE_SHARE = 0.20

FLOW_CANARY_PRIORITY = (
    "market-sizing",
    "panelbot",
    "compere",
)

WORK_SPECIAL_WORKLOAD_BUCKET_OWNERS = frozenset(
    (
        "work-special-comms",
        "work-special-drive",
        "work-special-mail",
        "work-special-meetings",
    )
)

ROUTE_RECEIPT_REQUIRED_FIELDS = (
    "receipt_id",
    "receipt_source",
    "previous_receipt_hash",
    "receipt_hash",
    "synthetic",
    "created_at",
    "owner_tui",
    "prompt_id",
    "benchmark_skill_id",
    "requested_action",
    "selected_model_tier",
    "selected_model",
    "routing_score",
    "routing_bands",
    "allowed_role",
    "validator_gate",
    "escalation_trigger",
    "fallback_used",
    "estimated_cost_usd",
    "baseline_all_5_5_cost_usd",
    "validator_passed",
    "manual_override",
    "boundary_violation",
    "latency_ms",
    "operator_approval_required",
    "final_authority_required",
    "live_write_attempted",
    "outcome",
    "evidence_refs",
)

ROUTE_RECEIPT_STRICT_NONEMPTY_FIELDS = (
    "receipt_id",
    "receipt_source",
    "owner_tui",
    "prompt_id",
    "task_class",
    "requested_action",
    "selected_provider",
    "observed_provider",
    "selected_model",
    "observed_model",
    "selected_model_tier",
    "allowed_role",
    "validator_gate",
    "policy_id",
    "policy_hash",
    "policy_lifecycle_state",
    "provider_request_id",
    "independent_validator_id",
    "visible_response_ref",
    "cost_evidence_ref",
    "receipt_key_id",
    "receipt_signature",
    "receipt_signature_algorithm",
    "segment_root",
)

ROUTE_RECEIPT_REMOTE_OWNER_HOSTS = {
    "market-sizing": "work-special",
    "panelbot": "work-special",
    "compere": "work-special",
}

ROUTE_RECEIPT_REMOTE_HOSTS = {
    "work-special": os.environ.get(
        "NORMAN_ROUTE_RECEIPT_WORK_SPECIAL_SSH_TARGET", "root@192.168.2.147"
    ).strip()
    or "root@192.168.2.147",
}

ROUTE_RECEIPT_REMOTE_CONNECT_TIMEOUT_SECONDS = (
    os.environ.get("NORMAN_ROUTE_RECEIPT_SSH_CONNECT_TIMEOUT", "10").strip() or "10"
)


OPENAI_DIRECT_PRICING_USD_PER_1M = {
    "gpt-5.5": {"input": 5.00, "cached_input": 0.50, "output": 30.00},
    "gpt-5.4": {"input": 2.50, "cached_input": 0.25, "output": 15.00},
    "gpt-5.4-mini": {"input": 0.75, "cached_input": 0.075, "output": 4.50},
}


BEDROCK_US_EAST_2_PRICING_USD_PER_1M = {
    "openai.gpt-5.5": {"input": 5.50, "cached_input": 0.55, "output": 33.00},
    "openai.gpt-5.4": {"input": 2.75, "cached_input": 0.275, "output": 16.50},
}


ARCHITECTURE_MODES = {
    "hybrid": {
        "label": "Hybrid guarded loop",
        "description": (
            "Local deterministic checks first; mini/cheap worker only for bounded "
            "background cleanup; GPT-5.4 owns normal verifier gates and GPT-5.5 "
            "is reserved for final-authority escalation."
        ),
        "token_split": {
            "local": 0.0,
            "planner_5_4": 0.25,
            "worker_mini": 0.60,
            "verifier_5_4": 0.15,
        },
        "estimated_cost_ratio_vs_direct_5_5_flex": 0.49,
        "user_selectable": True,
        "mode_guard": "Worker output is draft-only unless the 5.4 verifier accepts it; 5.5 is final authority only.",
    },
    "full-5-5": {
        "label": "Full GPT-5.5 loop",
        "description": (
            "All model-eligible reasoning, drafting, verification, and final synthesis "
            "stay on GPT-5.5."
        ),
        "token_split": {
            "local": 0.0,
            "planner_5_5": 1.0,
            "worker_mini": 0.0,
            "verifier_5_5": 0.0,
        },
        "estimated_cost_ratio_vs_direct_5_5_flex": 1.0,
        "user_selectable": True,
        "mode_guard": "Highest-confidence mode; no cheap-worker savings.",
    },
}


@dataclass(frozen=True)
class LoopTarget:
    slug: str
    label: str
    url: str
    repo_hint: str
    ownership: str
    approval_boundary: str
    blocked_automatic_actions: tuple[str, ...]
    first_fast_checks: tuple[str, ...]
    continuous_loop_goal: str
    expected_runtime: str = EXPECTED_RUNTIME
    expected_model: str = EXPECTED_MODEL


@dataclass
class StatusSnapshot:
    slug: str
    url: str
    reachable: bool
    state: str = ""
    pending: bool = False
    queue_depth: int = 0
    ui_version: str = ""
    selected_runtime: str = ""
    selected_model: str = ""
    status_message: str = ""
    last_error: str = ""
    error: str = ""
    bbs_actor: str = ""
    bbs_state: str = ""
    bbs_summary: str = ""
    bbs_activity: str = ""
    bbs_waiting_pickup: int = 0
    bbs_picked_up: int = 0
    bbs_missing_context: int = 0
    bbs_actionable_high: int = 0
    bbs_actionable_urgent: int = 0
    bbs_error: str = ""


@dataclass(frozen=True)
class LoopMove:
    move_id: str
    lane: str
    priority: str
    automatic: bool
    approval_required: bool
    model_lane: str
    reason: str
    evidence: tuple[str, ...]
    next_action: str


LOOP_TARGETS: dict[str, LoopTarget] = {
    "control-plane": LoopTarget(
        slug="control-plane",
        label="Control Plane",
        url="https://cp.kris.openbrand.com/api/status",
        repo_hint="/home/operator/code/control_plane",
        ownership=(
            "GAPI admin, GAPI DB, WebGOAT, QuickSight dataset/build surfaces, "
            "Armitage evidence/runbooks, shared cleanup pipelines"
        ),
        approval_boundary=(
            "No autonomous paid resource, seat, quota, workflow-cost, access, "
            "deploy, or restart change."
        ),
        blocked_automatic_actions=(
            "deploy",
            "restart service",
            "change route/model",
            "modify auth",
            "run paid/volume-expanding workflow",
            "use HAL for background discovery",
        ),
        first_fast_checks=(
            "read /api/status",
            "confirm Bedrock Codex 5.5 route",
            "check pending/queue_depth",
            "classify last_error",
            "prepare owner-lane evidence packet",
        ),
        continuous_loop_goal=(
            "Keep CP ready to handle obvious route, queue, auth-artifact, and "
            "runbook triage moves without dispatching unsafe live mutations."
        ),
    ),
    "gold-book": LoopTarget(
        slug="gold-book",
        label="Gold Book",
        url="https://goldbook.kris.openbrand.com/api/status",
        repo_hint="/home/operator/code/gold_book",
        ownership=(
            "Gold Book generation, getspecs, writespecs, GTIN repair, and live "
            "Google Sheet SpecMasters"
        ),
        approval_boundary=(
            "No autonomous paid research, enrichment, data-vendor, publication, "
            "live Sheet, deploy, or restart change."
        ),
        blocked_automatic_actions=(
            "publish externally",
            "modify live SpecMasters",
            "run paid enrichment",
            "change route/model",
            "restart service",
            "use HAL for background discovery",
        ),
        first_fast_checks=(
            "read /api/status",
            "confirm Bedrock Codex 5.5 route",
            "check pending/queue_depth",
            "classify last_error",
            "prepare Gold Book preflight packet",
        ),
        continuous_loop_goal=(
            "Keep Gold Book ready for continuous reference-work triage while "
            "preserving source provenance and live Sheet boundaries."
        ),
    ),
    "networking": LoopTarget(
        slug="networking",
        label="NetOps",
        url="http://192.168.2.242:8791/api/status",
        repo_hint="/home/debian/networking",
        ownership=(
            "LAN, firewall, routes, Proxmox/host access, network-adjacent "
            "service reachability, and cross-lane connectivity handoffs"
        ),
        approval_boundary=(
            "No autonomous ISP, carrier, DNS, firewall, relay, tunnel, route, "
            "host cleanup, deploy, restart, or paid connectivity change."
        ),
        blocked_automatic_actions=(
            "ACK BBS handoff",
            "change firewall",
            "change DNS",
            "restart network service",
            "delete operational data",
            "modify tunnel/relay",
            "take over another owner lane",
        ),
        first_fast_checks=(
            "read /api/status",
            "read /api/bbs/summary",
            "classify missing-context handoffs",
            "check route and queue state",
            "prepare owner-lane evidence packet",
        ),
        continuous_loop_goal=(
            "Keep NetOps handoffs triaged quickly while preventing blind ACKs, "
            "unsafe cleanup, and connectivity mutations without approval."
        ),
        expected_model=EXPECTED_MODEL,
    ),
    "phone-ops": LoopTarget(
        slug="phone-ops",
        label="Phone Ops",
        url="https://phone.home.arpa/api/status",
        repo_hint="/opt/phone-ops",
        ownership=(
            "Phone/tablet/kiosk app flows, Mothbox mobile checks, IPA pulls, "
            "device-facing support, and PhoneOps-to-NetOps handoffs"
        ),
        approval_boundary=(
            "No autonomous App Store/account change, paid mobile workflow, "
            "device enrollment, deploy, restart, firewall request execution, or "
            "cross-lane takeover."
        ),
        blocked_automatic_actions=(
            "ACK BBS handoff",
            "install mobile app",
            "change App Store/account state",
            "restart service",
            "modify firewall or network route",
            "take over NetOps task",
        ),
        first_fast_checks=(
            "read /api/status",
            "read /api/bbs/summary",
            "classify PhoneOps/NetOps handoff state",
            "check route and queue state",
            "prepare device evidence packet",
        ),
        continuous_loop_goal=(
            "Keep phone/device tickets moving through clear evidence packets and "
            "handoffs without performing account, install, or network mutations."
        ),
        expected_model=EXPECTED_MODEL,
    ),
}


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _fetch_json(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "norman-work-loop-canary/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _bbs_url_for_status_url(url: str) -> str:
    if url.endswith("/api/status"):
        return f"{url[:-len('/api/status')]}/api/bbs/summary?refresh=1"
    if "/api/status?" in url:
        return f"{url.split('/api/status?', 1)[0]}/api/bbs/summary?refresh=1"
    return url.rstrip("/") + "/api/bbs/summary?refresh=1"


def fetch_statuses(
    targets: dict[str, LoopTarget], timeout: float
) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for slug, target in targets.items():
        try:
            item = _fetch_json(target.url, timeout)
            item["_loop_slug"] = slug
            item["_loop_url"] = target.url
            try:
                item["_bbs_summary"] = _fetch_json(
                    _bbs_url_for_status_url(target.url), timeout
                )
            except (
                OSError,
                urllib.error.URLError,
                TimeoutError,
                json.JSONDecodeError,
            ) as exc:
                item["_bbs_error"] = f"{type(exc).__name__}: {exc}"
            statuses.append(item)
        except (
            OSError,
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            statuses.append(
                {
                    "_loop_slug": slug,
                    "_loop_url": target.url,
                    "_loop_error": f"{type(exc).__name__}: {exc}",
                }
            )
    return statuses


def load_status_source(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("statuses"), list):
        return [row for row in data["statuses"] if isinstance(row, dict)]
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        return [row for row in data["rows"] if isinstance(row, dict)]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    raise ValueError(f"{path} does not contain statuses/rows")


def _snapshot_from_status(item: dict[str, Any]) -> StatusSnapshot:
    slug = str(item.get("_loop_slug") or item.get("slug") or item.get("name") or "")
    target = LOOP_TARGETS.get(slug)
    url = str(
        item.get("_loop_url") or item.get("url") or (target.url if target else "")
    )
    error = str(item.get("_loop_error") or item.get("error") or "")
    if error:
        return StatusSnapshot(slug=slug, url=url, reachable=False, error=error)
    bbs_summary = item.get("_bbs_summary") or item.get("bbs_summary") or {}
    if not isinstance(bbs_summary, dict):
        bbs_summary = {}
    bbs_counts = bbs_summary.get("counts")
    if not isinstance(bbs_counts, dict):
        bbs_counts = {}
    bbs_handoff = bbs_summary.get("handoff")
    if not isinstance(bbs_handoff, dict):
        bbs_handoff = {}
    return StatusSnapshot(
        slug=slug,
        url=url,
        reachable=True,
        state=str(item.get("state") or item.get("status") or ""),
        pending=bool(item.get("pending")),
        queue_depth=_coerce_int(item.get("queue_depth")),
        ui_version=str(item.get("ui_version") or ""),
        selected_runtime=str(item.get("selected_runtime") or ""),
        selected_model=str(item.get("selected_model") or ""),
        status_message=str(item.get("status_message") or ""),
        last_error=str(item.get("last_error") or ""),
        bbs_actor=str(bbs_summary.get("actor") or ""),
        bbs_state=str(bbs_summary.get("state") or bbs_handoff.get("state") or ""),
        bbs_summary=str(bbs_summary.get("summary") or bbs_handoff.get("summary") or ""),
        bbs_activity=str(bbs_summary.get("activity") or ""),
        bbs_waiting_pickup=_coerce_int(bbs_counts.get("waiting_pickup")),
        bbs_picked_up=_coerce_int(bbs_counts.get("picked_up")),
        bbs_missing_context=_coerce_int(bbs_counts.get("missing_context")),
        bbs_actionable_high=_coerce_int(bbs_counts.get("actionable_high")),
        bbs_actionable_urgent=_coerce_int(bbs_counts.get("actionable_urgent")),
        bbs_error=str(item.get("_bbs_error") or ""),
    )


def _route_ok(snapshot: StatusSnapshot, target: LoopTarget | None = None) -> bool:
    expected_runtime = target.expected_runtime if target else EXPECTED_RUNTIME
    expected_model = target.expected_model if target else EXPECTED_MODEL
    return (
        snapshot.selected_runtime == expected_runtime
        and snapshot.selected_model == expected_model
    )


def _status_evidence(snapshot: StatusSnapshot) -> tuple[str, ...]:
    evidence = [
        f"reachable={snapshot.reachable}",
        f"state={snapshot.state or 'unknown'}",
        f"pending={snapshot.pending}",
        f"queue_depth={snapshot.queue_depth}",
    ]
    if snapshot.ui_version:
        evidence.append(f"ui_version={snapshot.ui_version}")
    if snapshot.selected_runtime or snapshot.selected_model:
        evidence.append(
            f"route={snapshot.selected_runtime or 'unknown'}/"
            f"{snapshot.selected_model or 'unknown'}"
        )
    if snapshot.status_message:
        evidence.append(f"status_message={snapshot.status_message}")
    if snapshot.last_error:
        evidence.append(f"last_error={snapshot.last_error}")
    if snapshot.error:
        evidence.append(f"error={snapshot.error}")
    if snapshot.bbs_summary or snapshot.bbs_state or snapshot.bbs_error:
        evidence.append(f"bbs_state={snapshot.bbs_state or 'unknown'}")
        evidence.append(f"bbs_summary={snapshot.bbs_summary or 'none'}")
        evidence.append(f"bbs_waiting_pickup={snapshot.bbs_waiting_pickup}")
        evidence.append(f"bbs_missing_context={snapshot.bbs_missing_context}")
        evidence.append(f"bbs_picked_up={snapshot.bbs_picked_up}")
        evidence.append(f"bbs_actionable_high={snapshot.bbs_actionable_high}")
        evidence.append(f"bbs_actionable_urgent={snapshot.bbs_actionable_urgent}")
    if snapshot.bbs_error:
        evidence.append(f"bbs_error={snapshot.bbs_error}")
    return tuple(evidence)


def _classify_error(text: str) -> str:
    lower = text.lower()
    if any(word in lower for word in ("usage", "quota", "limit", "rate limit")):
        return "usage_or_quota"
    if any(word in lower for word in ("auth", "credential", "cookie", "token", "sso")):
        return "auth_artifact"
    if any(word in lower for word in ("timeout", "timed out", "504", "502", "503")):
        return "transient_route"
    if any(word in lower for word in ("model", "unsupported", "provider", "bedrock")):
        return "model_route"
    return "general_error"


def classify_moves(target: LoopTarget, snapshot: StatusSnapshot) -> list[LoopMove]:
    evidence = _status_evidence(snapshot)
    moves: list[LoopMove] = [
        LoopMove(
            move_id="l0_status_probe",
            lane="local-deterministic",
            priority="P0",
            automatic=True,
            approval_required=False,
            model_lane="none",
            reason="Read-only health check is always safe for the loop.",
            evidence=evidence,
            next_action="Keep polling the status endpoint on the fast cadence.",
        ),
        LoopMove(
            move_id="hal_boundary_guard",
            lane="policy-guard",
            priority="P0",
            automatic=True,
            approval_required=False,
            model_lane="none",
            reason="HAL is not a background-discovery path for work-bot loops.",
            evidence=("HAL access stays explicit, operator-scoped, and non-durable.",),
            next_action=(
                "Use target host status, BBS, repo runbooks, and owner-lane APIs "
                "before any HAL-specific maintenance request."
            ),
        ),
    ]

    if not snapshot.reachable:
        moves.append(
            LoopMove(
                move_id="status_unreachable_packet",
                lane="owner-lane-evidence",
                priority="P0",
                automatic=True,
                approval_required=False,
                model_lane="cheap-summary-then-5.5-review",
                reason="The loop can gather route evidence, but must not restart blindly.",
                evidence=evidence,
                next_action=(
                    "Retry once, capture DNS/TLS/HTTP error class, then hand an "
                    "evidence packet to the owner lane."
                ),
            )
        )
        return moves

    if not _route_ok(snapshot, target):
        moves.append(
            LoopMove(
                move_id="route_mismatch_to_bedrock_5_5",
                lane="owner-lane-change-plan",
                priority="P0",
                automatic=False,
                approval_required=True,
                model_lane="5.5-xhigh-verifier",
                reason=(
                    f"{target.label} is expected on "
                    f"{target.expected_runtime}/{target.expected_model} for this loop."
                ),
                evidence=evidence,
                next_action=(
                    "Prepare a reversible route-change plan; execute only after "
                    "operator approval."
                ),
            )
        )
    else:
        moves.append(
            LoopMove(
                move_id="route_confirmed_expected_model",
                lane="local-deterministic",
                priority="P1",
                automatic=True,
                approval_required=False,
                model_lane="none",
                reason=(
                    "The target is already on the expected "
                    f"{target.expected_runtime}/{target.expected_model} route."
                ),
                evidence=evidence,
                next_action="No route change needed.",
            )
        )

    if snapshot.pending or snapshot.queue_depth > 0:
        moves.append(
            LoopMove(
                move_id="queue_watch_packet",
                lane="queue-triage",
                priority="P1",
                automatic=True,
                approval_required=False,
                model_lane="cheap-summary-then-5.5-review",
                reason="Queued work should be summarized before adding more load.",
                evidence=evidence,
                next_action=(
                    "Capture queue depth, status message, active handoff IDs, and "
                    "oldest age; do not enqueue new loop work until stale/active "
                    "state is clear."
                ),
            )
        )
    else:
        moves.append(
            LoopMove(
                move_id="idle_ready",
                lane="local-deterministic",
                priority="P2",
                automatic=True,
                approval_required=False,
                model_lane="none",
                reason="The target is healthy and idle.",
                evidence=evidence,
                next_action="Eligible for the next dry-run canary or approved job.",
            )
        )

    if snapshot.bbs_missing_context > 0:
        moves.append(
            LoopMove(
                move_id="bbs_missing_context_guard",
                lane="bbs-handoff-guard",
                priority="P0",
                automatic=True,
                approval_required=False,
                model_lane="none",
                reason="Waiting BBS handoffs are missing enough context for safe pickup.",
                evidence=evidence,
                next_action=(
                    "Do not ACK. Ask the creator to add body/evidence, or mark "
                    "BLOCKED with the missing-context reason if it cannot be recovered."
                ),
            )
        )
    elif snapshot.bbs_waiting_pickup > 0:
        moves.append(
            LoopMove(
                move_id="bbs_pickup_review_packet",
                lane="bbs-handoff-guard",
                priority="P1",
                automatic=True,
                approval_required=False,
                model_lane="5.5-review-if-owner-intends-pickup",
                reason="BBS has handoffs waiting for owner pickup.",
                evidence=evidence,
                next_action=(
                    "Show the handoff summary and helper commands; owner ACKs only "
                    "when actually taking the work."
                ),
            )
        )

    status_text_is_error = snapshot.state not in {"", "ok"} and bool(
        snapshot.status_message
    )
    error_text = " ".join(
        part
        for part in (
            snapshot.last_error,
            snapshot.status_message if status_text_is_error else "",
        )
        if part
    )
    if error_text:
        kind = _classify_error(error_text)
        moves.append(
            LoopMove(
                move_id=f"{kind}_triage",
                lane="error-triage",
                priority="P1",
                automatic=True,
                approval_required=False,
                model_lane="cheap-classifier-then-5.5-review",
                reason=f"Status text matches {kind}; classify before acting.",
                evidence=evidence,
                next_action=(
                    "Collect the matching auth/route/quota/service evidence and "
                    "escalate only the smallest reversible fix."
                ),
            )
        )

    moves.append(
        LoopMove(
            move_id="approval_boundary",
            lane="authority-guard",
            priority="P0",
            automatic=True,
            approval_required=False,
            model_lane="none",
            reason=target.approval_boundary,
            evidence=tuple(
                f"blocked_auto_action={item}"
                for item in target.blocked_automatic_actions
            ),
            next_action=(
                "The loop may propose or prepare evidence for these actions; it "
                "must not execute them without explicit approval."
            ),
        )
    )
    return moves


def _bbs_blocks_new_loop_work(snapshot: StatusSnapshot) -> bool:
    return (
        snapshot.bbs_missing_context > 0
        or snapshot.bbs_waiting_pickup > 0
        or snapshot.bbs_actionable_urgent > 0
    )


def _loop_ready(snapshot: StatusSnapshot, target: LoopTarget) -> bool:
    return (
        snapshot.reachable
        and snapshot.state == "ok"
        and not snapshot.pending
        and snapshot.queue_depth == 0
        and _route_ok(snapshot, target)
        and not snapshot.last_error
        and not _bbs_blocks_new_loop_work(snapshot)
    )


def confidence_score(
    snapshot: StatusSnapshot, moves: list[LoopMove], target: LoopTarget
) -> int:
    score = 100
    if not snapshot.reachable:
        score -= 35
    if snapshot.reachable and snapshot.state != "ok":
        score -= 20
    if not _route_ok(snapshot, target):
        score -= 25
    if snapshot.pending or snapshot.queue_depth > 0:
        score -= 20
    if snapshot.last_error:
        score -= 20
    if snapshot.bbs_missing_context > 0:
        score -= 25
    elif snapshot.bbs_waiting_pickup > 0:
        score -= 15
    if snapshot.bbs_actionable_urgent > 0:
        score -= 20
    if any(move.approval_required for move in moves):
        score -= 10
    return max(0, min(100, score))


def confidence_band(score: int) -> str:
    if score >= 85:
        return "green"
    if score >= 65:
        return "yellow"
    return "red"


def build_loop_architecture() -> list[dict[str, Any]]:
    return [
        {
            "tier": "L0",
            "name": "deterministic fast path",
            "cadence": "1-5 minutes",
            "model": "none",
            "purpose": (
                "Status, queue depth, route, last_error, BBS age, and obvious "
                "ownership classification."
            ),
            "safe_automatic_actions": [
                "read status endpoints",
                "dedupe stale handoff alerts",
                "build evidence packets",
                "skip loop work when queue is active",
            ],
        },
        {
            "tier": "L1",
            "name": "cheap worker lane",
            "cadence": "on L0 trigger",
            "model": "mini or cheaper Bedrock/Claude candidate",
            "purpose": (
                "Compress logs, summarize large numeric tables, draft ticket "
                "cleanup packets, and propose next checks."
            ),
            "safe_automatic_actions": [
                "summarize",
                "classify",
                "extract commands already present in runbooks",
                "produce JSON evidence bundles",
            ],
        },
        {
            "tier": "L2",
            "name": "5.4 verifier",
            "cadence": "when action has blast radius or ambiguity",
            "model": "Bedrock Codex 5.4 high/xhigh",
            "purpose": (
                "Review cheap-lane output for authority, missing evidence, unsafe "
                "HAL usage, deploy/restart risk, and runbook fit."
            ),
            "safe_automatic_actions": [
                "approve dry-run next step",
                "reject unsafe packet",
                "request missing evidence",
            ],
        },
        {
            "tier": "L3",
            "name": "owner-lane execution",
            "cadence": "operator-approved only",
            "model": "owning TUI route",
            "purpose": "Execute deploys, restarts, live Sheet writes, paid runs, or auth changes.",
            "safe_automatic_actions": [],
        },
    ]


def _token_cost_usd(
    pricing: dict[str, float], input_tokens: int, output_tokens: int
) -> float:
    return round(
        (input_tokens / 1_000_000 * pricing["input"])
        + (output_tokens / 1_000_000 * pricing["output"]),
        6,
    )


def _direct_flex_cost_usd(
    model: str, input_tokens: int, output_tokens: int
) -> float | None:
    pricing = OPENAI_DIRECT_PRICING_USD_PER_1M.get(model)
    if pricing is None:
        return None
    flex_pricing = {
        "input": pricing["input"] * 0.5,
        "output": pricing["output"] * 0.5,
    }
    return _token_cost_usd(flex_pricing, input_tokens, output_tokens)


def _bedrock_cost_usd(
    model: str, input_tokens: int, output_tokens: int
) -> float | None:
    pricing = BEDROCK_US_EAST_2_PRICING_USD_PER_1M.get(model)
    if pricing is None:
        return None
    return _token_cost_usd(pricing, input_tokens, output_tokens)


def build_cost_basis(mode: str) -> dict[str, Any]:
    if mode not in ARCHITECTURE_MODES:
        raise ValueError(f"unknown architecture mode: {mode}")
    selected = ARCHITECTURE_MODES[mode]
    full_direct = _direct_flex_cost_usd(
        "gpt-5.5", SAMPLE_INPUT_TOKENS, SAMPLE_OUTPUT_TOKENS
    )
    hybrid_ratio = float(
        ARCHITECTURE_MODES["hybrid"]["estimated_cost_ratio_vs_direct_5_5_flex"]
    )
    selected_ratio = float(selected["estimated_cost_ratio_vs_direct_5_5_flex"])
    full_bedrock = _bedrock_cost_usd(
        "openai.gpt-5.5", SAMPLE_INPUT_TOKENS, SAMPLE_OUTPUT_TOKENS
    )
    mini_worker_direct = _direct_flex_cost_usd(
        "gpt-5.4-mini", SAMPLE_INPUT_TOKENS, SAMPLE_OUTPUT_TOKENS
    )
    full_direct_value = float(full_direct or 0.0)
    return {
        "estimate_label": "estimated USD; not invoice-reconciled",
        "mode": mode,
        "selected_mode": selected,
        "status_loop_model_calls": 0,
        "status_loop_estimated_usd": 0.0,
        "sample_ticket_cleanup": {
            "input_tokens": SAMPLE_INPUT_TOKENS,
            "output_tokens": SAMPLE_OUTPUT_TOKENS,
            "full_direct_5_5_flex_usd": full_direct,
            "hybrid_direct_estimated_usd": round(full_direct_value * hybrid_ratio, 6),
            "selected_mode_direct_estimated_usd": round(
                full_direct_value * selected_ratio, 6
            ),
            "full_bedrock_5_5_us_east_2_usd": full_bedrock,
            "mini_worker_direct_flex_usd_if_all_worker": mini_worker_direct,
            "hybrid_ratio_vs_direct_5_5_flex": hybrid_ratio,
            "selected_ratio_vs_direct_5_5_flex": selected_ratio,
        },
        "pricing_sources": [
            {
                "provider": "OpenAI direct API",
                "url": "https://openai.com/api/pricing/",
                "notes": (
                    "GPT-5.5, GPT-5.4, GPT-5.4 mini standard token rates; "
                    "Flex/Batch are lower-cost processing modes. Report uses "
                    "the normalized benchmark baseline of direct GPT-5.5 Flex."
                ),
            },
            {
                "provider": "AWS Bedrock",
                "url": "https://aws.amazon.com/bedrock/pricing/",
                "notes": (
                    "OpenAI GPT-5.5 and GPT-5.4 us-east-2 on-demand token rates. "
                    "Actual account invoices may vary by region, discounts, cache, "
                    "and service tier."
                ),
            },
        ],
    }


def build_always_on_plan(
    *,
    mode: str,
    fast_loop_interval_seconds: int = DEFAULT_FAST_LOOP_INTERVAL_SECONDS,
    max_changed_tickets_per_cycle: int = DEFAULT_MAX_CHANGED_TICKETS_PER_CYCLE,
    daily_budget_usd: float = DEFAULT_DAILY_BUDGET_USD,
) -> dict[str, Any]:
    if mode not in ARCHITECTURE_MODES:
        raise ValueError(f"unknown architecture mode: {mode}")
    interval = max(30, int(fast_loop_interval_seconds or 0))
    changed_limit = max(0, int(max_changed_tickets_per_cycle or 0))
    daily_budget = max(0.0, float(daily_budget_usd or 0.0))
    cost_basis = build_cost_basis(mode)
    sample = cost_basis["sample_ticket_cleanup"]
    selected_sample = float(sample["selected_mode_direct_estimated_usd"] or 0.0)
    if mode == "hybrid":
        expected_multiplier = 2.5
        p95_multiplier = 6.0
        confidence = "medium-low"
    else:
        expected_multiplier = 1.6
        p95_multiplier = 3.0
        confidence = "medium"
    expected_ticket = round(selected_sample * expected_multiplier, 6)
    p95_ticket = round(selected_sample * p95_multiplier, 6)
    expected_cycle = round(expected_ticket * changed_limit, 6)
    p95_cycle = round(p95_ticket * changed_limit, 6)
    cycles_per_day = round(86_400 / interval, 2)

    def affordable_cycles(amount: float) -> int | None:
        if amount <= 0:
            return None
        return int(daily_budget // amount)

    expected_cycles = affordable_cycles(expected_cycle)
    p95_cycles = affordable_cycles(p95_cycle)
    spend_gate = "ready"
    spend_reasons: list[str] = []
    if changed_limit <= 0:
        spend_gate = "hold"
        spend_reasons.append("max_changed_tickets_per_cycle is zero")
    if daily_budget <= 0:
        spend_gate = "hold"
        spend_reasons.append("daily_budget_usd is zero")
    elif p95_cycle > daily_budget:
        spend_gate = "hold"
        spend_reasons.append("p95 changed-ticket cycle exceeds daily budget")
    if not spend_reasons:
        spend_reasons.append(
            "daily budget can absorb at least one p95 changed-ticket cycle"
        )

    return {
        "schema": "norman.always-on-loop-plan.v1",
        "fast_loop_interval_seconds": interval,
        "fast_loop_cycles_per_day": cycles_per_day,
        "status_loop_model_calls": 0,
        "unchanged_daily_usd": 0.0,
        "max_changed_tickets_per_cycle": changed_limit,
        "daily_budget_usd": daily_budget,
        "sample_ticket_input_tokens": SAMPLE_INPUT_TOKENS,
        "sample_ticket_output_tokens": SAMPLE_OUTPUT_TOKENS,
        "observed_rate_card_usd_per_changed_ticket": selected_sample,
        "expected_usd_per_changed_ticket": expected_ticket,
        "p95_usd_per_changed_ticket": p95_ticket,
        "expected_usd_per_changed_cycle": expected_cycle,
        "p95_usd_per_changed_cycle": p95_cycle,
        "expected_changed_cycles_affordable_per_day": expected_cycles,
        "p95_changed_cycles_affordable_per_day": p95_cycles,
        "cost_confidence": confidence,
        "spend_gate": spend_gate,
        "spend_gate_reasons": spend_reasons,
        "operator_approval_required_for_live_enable": True,
        "hard_stops": [
            "route mismatch",
            "queue active or pending",
            "last_error present",
            "BBS missing context",
            "BBS waiting pickup",
            "approval-required move",
            "p95 cycle exceeds daily budget",
        ],
    }


def build_report(
    statuses: list[dict[str, Any]],
    *,
    source: str = "",
    mode: str = DEFAULT_MODE,
    fast_loop_interval_seconds: int = DEFAULT_FAST_LOOP_INTERVAL_SECONDS,
    max_changed_tickets_per_cycle: int = DEFAULT_MAX_CHANGED_TICKETS_PER_CYCLE,
    daily_budget_usd: float = DEFAULT_DAILY_BUDGET_USD,
) -> dict[str, Any]:
    snapshots = [_snapshot_from_status(item) for item in statuses]
    target_rows = []
    for snapshot in snapshots:
        target = LOOP_TARGETS.get(snapshot.slug)
        if target is None:
            continue
        moves = classify_moves(target, snapshot)
        target_confidence = confidence_score(snapshot, moves, target)
        route_ok = _route_ok(snapshot, target)
        target_rows.append(
            {
                "target": asdict(target),
                "status": asdict(snapshot),
                "moves": [asdict(move) for move in moves],
                "route_ok": route_ok,
                "loop_ready": _loop_ready(snapshot, target),
                "optimizer_confidence_score": target_confidence,
                "optimizer_confidence_band": confidence_band(target_confidence),
                "blocks_new_loop_work": _bbs_blocks_new_loop_work(snapshot),
                "fast_checks": list(target.first_fast_checks),
            }
        )

    confidence_scores = [
        _coerce_int(row.get("optimizer_confidence_score")) for row in target_rows
    ]
    approval_required_moves = sum(
        1 for row in target_rows for move in row["moves"] if move["approval_required"]
    )
    always_on_plan = build_always_on_plan(
        mode=mode,
        fast_loop_interval_seconds=fast_loop_interval_seconds,
        max_changed_tickets_per_cycle=max_changed_tickets_per_cycle,
        daily_budget_usd=daily_budget_usd,
    )
    shadow_ready = (
        target_rows
        and all(
            row["loop_ready"] and row["optimizer_confidence_band"] == "green"
            for row in target_rows
        )
        and approval_required_moves == 0
    )
    always_on_shadow_gate = (
        "ready" if shadow_ready and always_on_plan["spend_gate"] == "ready" else "hold"
    )
    summary = {
        "targets": len(target_rows),
        "reachable": sum(1 for row in target_rows if row["status"]["reachable"]),
        "route_ok": sum(1 for row in target_rows if row["route_ok"]),
        "idle_ready": sum(1 for row in target_rows if row["loop_ready"]),
        "optimizer_ready": sum(
            1
            for row in target_rows
            if row["loop_ready"] and row["optimizer_confidence_band"] == "green"
        ),
        "approval_required_moves": approval_required_moves,
        "automatic_moves": sum(
            1 for row in target_rows for move in row["moves"] if move["automatic"]
        ),
        "bbs_missing_context_targets": sum(
            1
            for row in target_rows
            if _coerce_int(row["status"].get("bbs_missing_context")) > 0
        ),
        "bbs_waiting_pickup_targets": sum(
            1
            for row in target_rows
            if _coerce_int(row["status"].get("bbs_waiting_pickup")) > 0
        ),
        "confidence_min": min(confidence_scores) if confidence_scores else 0,
        "confidence_avg": round(sum(confidence_scores) / len(confidence_scores), 1)
        if confidence_scores
        else 0.0,
        "shadow_rollout_recommendation": "ready" if shadow_ready else "hold",
        "always_on_shadow_gate": always_on_shadow_gate,
        "always_on_live_enable_requires_approval": True,
        "hal_background_discovery_allowed": False,
        "continuous_loop_enabled": False,
    }
    return {
        "schema": "norman.work-loop-canary.v1",
        "generated_at": int(time.time()),
        "source": source,
        "expected_runtime": EXPECTED_RUNTIME,
        "expected_model": EXPECTED_MODEL,
        "architecture_mode": mode,
        "cost_basis": build_cost_basis(mode),
        "always_on_plan": always_on_plan,
        "architecture_modes": ARCHITECTURE_MODES,
        "summary": summary,
        "architecture": build_loop_architecture(),
        "rows": target_rows,
    }


def load_skill_matrix_source(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    if data.get("schema") != "norman.work-domain-skill-benchmark.v1":
        raise ValueError(f"{path} is not a work-domain skill benchmark")
    return data


def _owner_summary_row(owner: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "owner_tui": owner,
        "domains": list(item.get("domains") or []),
        "skill_count": _coerce_int(item.get("skill_count")),
        "recommended_canary_tier": str(item.get("recommended_canary_tier") or ""),
        "rationale": str(item.get("rationale") or ""),
        "comfortable_lower_final_count": _coerce_int(
            item.get("comfortable_shadow_lower_model_final_count")
        ),
        "lower_worker_or_draft_count": _coerce_int(
            item.get("lower_model_worker_or_draft_count")
        ),
        "bedrock_5_4_xhigh_count": _coerce_int(item.get("bedrock_5_4_xhigh_count")),
        "bedrock_5_5_xhigh_count": _coerce_int(item.get("bedrock_5_5_xhigh_count")),
    }


def _is_workload_bucket_owner(owner: str) -> bool:
    return owner in WORK_SPECIAL_WORKLOAD_BUCKET_OWNERS


def _flow_workload_bucket_rows(owner_summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for owner in sorted(WORK_SPECIAL_WORKLOAD_BUCKET_OWNERS):
        item = owner_summary.get(owner)
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                **_owner_summary_row(owner, item),
                "target_kind": "workload_bucket",
                "deployable_owner": False,
                "mapping_required": (
                    "Map this workload bucket to a concrete work-special TUI owner "
                    "before deployment, route receipt capture, or cutover scoring."
                ),
            }
        )
    return rows


def _flow_launch_gate(owner_row: dict[str, Any]) -> str:
    tier = owner_row["recommended_canary_tier"]
    if tier == "first_canary":
        return "ready_for_shadow_route_receipts"
    if tier == "shadow_with_5_4_verifier" and owner_row["bedrock_5_5_xhigh_count"] == 0:
        return "ready_for_5_4_shadow_verifier"
    if tier == "shadow_only_until_more_validators":
        return "hold_until_validator_receipts"
    return "hold_final_authority"


def _flow_wave_for_owner(owner_row: dict[str, Any]) -> int:
    gate = _flow_launch_gate(owner_row)
    if gate == "ready_for_shadow_route_receipts":
        return 1
    if gate == "ready_for_5_4_shadow_verifier":
        return 2
    if gate == "hold_until_validator_receipts":
        return 3
    return 4


def _flow_target_mode(owner_row: dict[str, Any]) -> str:
    gate = _flow_launch_gate(owner_row)
    if gate == "ready_for_shadow_route_receipts":
        return "lower_or_medium_route_receipts_only"
    if gate == "ready_for_5_4_shadow_verifier":
        return "5_4_verifier_shadow_receipts"
    if gate == "hold_until_validator_receipts":
        return "validator_gap_shadow_only"
    return "final_authority_dry_run_only"


def _ordered_flow_owners(
    owner_summary: dict[str, Any], requested_owners: tuple[str, ...]
) -> list[str]:
    if requested_owners:
        unknown = [owner for owner in requested_owners if owner not in owner_summary]
        if unknown:
            raise ValueError(f"unknown flow owner(s): {', '.join(unknown)}")
        workload_buckets = [
            owner for owner in requested_owners if _is_workload_bucket_owner(owner)
        ]
        if workload_buckets:
            raise ValueError(
                "flow owner(s) are workload buckets, not deployable TUIs: "
                + ", ".join(workload_buckets)
            )
        return list(requested_owners)

    selected = [
        owner
        for owner in FLOW_CANARY_PRIORITY
        if owner in owner_summary and not _is_workload_bucket_owner(owner)
    ]
    remaining_first_canaries = [
        owner
        for owner, item in owner_summary.items()
        if owner not in selected
        and not _is_workload_bucket_owner(owner)
        and str(item.get("recommended_canary_tier") or "") == "first_canary"
    ]
    return selected + sorted(remaining_first_canaries)


def build_flow_canary_plan(
    skill_matrix: dict[str, Any],
    *,
    requested_owners: tuple[str, ...] = (),
) -> dict[str, Any]:
    owner_summary = skill_matrix.get("summary_by_owner_tui")
    if not isinstance(owner_summary, dict):
        raise ValueError("skill matrix is missing summary_by_owner_tui")
    priority_focus_source = (
        skill_matrix.get("priority_focus")
        if isinstance(skill_matrix.get("priority_focus"), dict)
        else {}
    )

    selected_owners = _ordered_flow_owners(owner_summary, requested_owners)
    workload_buckets = _flow_workload_bucket_rows(owner_summary)
    targets = []
    for owner in selected_owners:
        item = owner_summary[owner]
        if not isinstance(item, dict):
            continue
        owner_row = _owner_summary_row(owner, item)
        wave = _flow_wave_for_owner(owner_row)
        targets.append(
            {
                **owner_row,
                "target_kind": "tui_owner",
                "deployable_owner": True,
                "wave": wave,
                "flow_mode": _flow_target_mode(owner_row),
                "launch_gate": _flow_launch_gate(owner_row),
                "route_receipt_sink": (f"{DEFAULT_ROUTE_RECEIPT_DIR}/{owner}.jsonl"),
                "allowed_actions": [
                    "read status and queue state",
                    "summarize bounded evidence",
                    "draft next-action packet",
                    "emit route receipt",
                ],
                "blocked_actions": [
                    "live write",
                    "BBS ACK/DONE/BLOCKED",
                    "service restart",
                    "deploy",
                    "DNS/Caddy/cloud/vendor mutation",
                    "external rollback or reopen",
                ],
                "promotion_gate": (
                    "50 route receipts or 24h with zero live-write attempts, "
                    "zero boundary violations, validator pass >= 98%, and "
                    "manual override rate <= 5%."
                )
                if wave == 1
                else (
                    "50 shadow verifier receipts with zero final-action attempts "
                    "and explicit 5.4 verifier accept/reject evidence."
                )
                if wave == 2
                else "Do not promote until validators or final-authority holds are resolved.",
            }
        )

    first_wave = [row["owner_tui"] for row in targets if row["wave"] == 1]
    second_wave = [row["owner_tui"] for row in targets if row["wave"] == 2]
    held_owners = sorted(
        owner
        for owner, item in owner_summary.items()
        if isinstance(item, dict)
        and not _is_workload_bucket_owner(owner)
        and str(item.get("recommended_canary_tier") or "").startswith("dry_run")
    )
    priority_focus_owners = [
        owner
        for owner in priority_focus_source.get("owners", [])
        if owner in owner_summary and not _is_workload_bucket_owner(owner)
    ]
    return {
        "schema": "norman.tui-flow-canary-plan.v1",
        "generated_at": int(time.time()),
        "source_schema": skill_matrix.get("schema"),
        "source_generated_at": skill_matrix.get("generated_at"),
        "dry_run_only": True,
        "deployment_ready_status": (
            "ready_for_shadow_route_receipts"
            if first_wave
            else "hold_no_first_canary_targets"
        ),
        "deployment_requires_operator_approval": True,
        "recommended_first_deploy_targets": first_wave,
        "recommended_second_wave_targets": second_wave,
        "held_final_authority_targets": held_owners,
        "priority_focus": {
            "domains": list(priority_focus_source.get("domains") or []),
            "owners": priority_focus_owners,
            "held_final_authority_owners": [
                owner for owner in priority_focus_owners if owner in held_owners
            ],
            "rationale": list(priority_focus_source.get("rationale") or []),
        },
        "workload_buckets_requiring_owner_mapping": workload_buckets,
        "summary": {
            "target_count": len(targets),
            "first_wave_count": len(first_wave),
            "second_wave_count": len(second_wave),
            "held_final_authority_count": len(held_owners),
            "workload_bucket_count": len(workload_buckets),
            "workload_bucket_skill_count": sum(
                _coerce_int(row.get("skill_count")) for row in workload_buckets
            ),
            "skill_matrix_skill_count": _coerce_int(skill_matrix.get("skill_count")),
            "modeled_savings_vs_all_bedrock_5_5_xhigh": skill_matrix.get(
                "summary", {}
            ).get("savings_vs_all_bedrock_5_5_xhigh"),
        },
        "route_receipt_contract": {
            "schema": "norman.tui-hybrid-route-receipt.v1",
            "required_fields": list(ROUTE_RECEIPT_REQUIRED_FIELDS),
            "invariants": [
                "live_write_attempted must be false in wave 1 and wave 2",
                "final_authority_required routes must stop before execution",
                "operator_approval_required must be true for deploy/restart/BBS close-loop/DNS/Caddy/cloud/vendor mutations",
                "fallback_used must name the failed tier and replacement tier",
                "evidence_refs must include validator, runbook, or status snapshot references",
            ],
        },
        "pre_deploy_checks": [
            "target TUI status endpoint returns ok",
            "queue depth is zero and no prompt is pending",
            "BBS missing-context and waiting-pickup counts are zero for the target",
            "route receipt sink is writable",
            "manual fallback to all-5.5 is available",
            "operator approves the web-only sync/restart command before deployment",
        ],
        "global_hard_stops": [
            "live write attempted",
            "BBS ACK/DONE/BLOCKED attempted",
            "service restart/deploy attempted without approval",
            "route mismatch without approved route plan",
            "validator missing or failing",
            "manual override rate above 5%",
            "cost estimate exceeds p95 daily budget",
        ],
        "promotion_metrics": [
            "route_receipt_count",
            "validator_pass_rate",
            "manual_override_rate",
            "fallback_rate",
            "cost_savings_vs_all_5_5",
            "latency_delta_vs_all_5_5",
            "boundary_violation_count",
            "operator_reported_bad_route_count",
        ],
        "targets": targets,
    }


def render_flow_canary_plan_markdown(plan: dict[str, Any]) -> str:
    summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
    priority_focus = (
        plan.get("priority_focus")
        if isinstance(plan.get("priority_focus"), dict)
        else {}
    )
    receipt = (
        plan.get("route_receipt_contract")
        if isinstance(plan.get("route_receipt_contract"), dict)
        else {}
    )
    lines = [
        "# TUI Flow Canary Plan",
        "",
        "Dry-run rollout plan. This does not deploy, restart, enqueue work, call models, ACK BBS handoffs, or mutate live state.",
        "",
        "## Summary",
        "",
        f"- Deployment status: {plan.get('deployment_ready_status')}",
        f"- Deployment requires approval: {plan.get('deployment_requires_operator_approval')}",
        f"- First deploy targets: {', '.join(plan.get('recommended_first_deploy_targets') or []) or '-'}",
        f"- Second wave targets: {', '.join(plan.get('recommended_second_wave_targets') or []) or '-'}",
        f"- Held final-authority targets: {', '.join(plan.get('held_final_authority_targets') or []) or '-'}",
        f"- Priority focus domains: {', '.join(priority_focus.get('domains') or []) or '-'}",
        f"- Priority focus owners: {', '.join(priority_focus.get('owners') or []) or '-'}",
        f"- Priority-focus held owners: {', '.join(priority_focus.get('held_final_authority_owners') or []) or '-'}",
        f"- Targets in plan: {summary.get('target_count')}",
        f"- Workload buckets needing owner mapping: {summary.get('workload_bucket_count')} ({summary.get('workload_bucket_skill_count')} skills)",
        f"- Skill matrix skills: {summary.get('skill_matrix_skill_count')}",
        f"- Modeled savings vs all Bedrock 5.5 xhigh: {float(summary.get('modeled_savings_vs_all_bedrock_5_5_xhigh') or 0.0) * 100:.1f}%",
        "",
        "## Priority Focus",
        "",
    ]
    lines.extend(f"- {item}" for item in priority_focus.get("rationale", []))
    lines.extend(
        [
            "",
            "## Route Receipt Contract",
            "",
            f"- Schema: {receipt.get('schema')}",
            "- Required fields: " + ", ".join(receipt.get("required_fields") or []),
            "- Invariants: " + "; ".join(receipt.get("invariants") or []),
            "",
            "## Pre-Deploy Checks",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in plan.get("pre_deploy_checks", []))
    workload_buckets = [
        row
        for row in plan.get("workload_buckets_requiring_owner_mapping", [])
        if isinstance(row, dict)
    ]
    if workload_buckets:
        lines.extend(
            [
                "",
                "## Workload Buckets Needing Owner Mapping",
                "",
                "| Bucket | Domains | Skills | Canary tier | Mapping required |",
                "|---|---|---:|---|---|",
            ]
        )
        for row in workload_buckets:
            lines.append(
                "| {bucket} | {domains} | {skills} | {tier} | {mapping} |".format(
                    bucket=_cell(row.get("owner_tui")),
                    domains=_cell(", ".join(row.get("domains") or [])),
                    skills=_coerce_int(row.get("skill_count")),
                    tier=_cell(row.get("recommended_canary_tier")),
                    mapping=_cell(row.get("mapping_required")),
                )
            )
    lines.extend(
        [
            "",
            "## Targets",
            "",
            "| Wave | Owner TUI | Gate | Flow mode | Skills | Lower final | 5.4 | 5.5 | Promotion gate |",
            "|---:|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in plan.get("targets", []):
        lines.append(
            "| {wave} | {owner} | {gate} | {mode} | {skills} | {lower} | {heavy} | {final} | {promotion} |".format(
                wave=row.get("wave"),
                owner=_cell(row.get("owner_tui")),
                gate=_cell(row.get("launch_gate")),
                mode=_cell(row.get("flow_mode")),
                skills=_coerce_int(row.get("skill_count")),
                lower=_coerce_int(row.get("comfortable_lower_final_count")),
                heavy=_coerce_int(row.get("bedrock_5_4_xhigh_count")),
                final=_coerce_int(row.get("bedrock_5_5_xhigh_count")),
                promotion=_cell(row.get("promotion_gate")),
            )
        )
    lines.extend(["", "## Hard Stops", ""])
    lines.extend(f"- {item}" for item in plan.get("global_hard_stops", []))
    lines.extend(["", "## Promotion Metrics", ""])
    lines.extend(f"- {item}" for item in plan.get("promotion_metrics", []))
    return "\n".join(lines) + "\n"


def load_flow_plan_source(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    if data.get("schema") != "norman.tui-flow-canary-plan.v1":
        raise ValueError(f"{path} is not a TUI flow canary plan")
    return data


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _safe_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonempty_sequence(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def _hex_digest(value: Any, *, length: int = 64) -> bool:
    clean = str(value or "").strip().lower()
    return len(clean) == length and all(char in "0123456789abcdef" for char in clean)


def _blankish(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "none", "false", "no", "0", "n/a"}
    return False


def _route_receipt_path(target_row: dict[str, Any], receipt_dir: Path) -> Path:
    owner = str(target_row.get("owner_tui") or "")
    if receipt_dir != DEFAULT_ROUTE_RECEIPT_DIR:
        return receipt_dir / f"{owner}.jsonl"
    sink = target_row.get("route_receipt_sink")
    if isinstance(sink, str) and sink:
        return Path(sink)
    return receipt_dir / f"{owner}.jsonl"


def load_route_receipts(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.exists():
        return [], [f"missing route receipt sink: {path}"]
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{line_no}: malformed JSON: {exc.msg}")
            continue
        if not isinstance(item, dict):
            errors.append(f"{path}:{line_no}: route receipt is not a JSON object")
            continue
        records.append(item)
    return records, errors


def route_receipt_canonical_payload(entry: dict[str, Any]) -> str:
    payload = dict(entry)
    payload.pop("receipt_hash", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def route_receipt_compute_hash(entry: dict[str, Any]) -> str:
    previous = str(entry.get("previous_receipt_hash") or "").strip()
    payload = route_receipt_canonical_payload(entry)
    return hashlib.sha256(f"{previous}\n{payload}".encode("utf-8")).hexdigest()


def route_receipt_chain_issues(receipts: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    previous_hash: str | None = None
    for index, receipt in enumerate(receipts, 1):
        saved_hash = str(receipt.get("receipt_hash") or "").strip()
        previous_receipt_hash = str(receipt.get("previous_receipt_hash") or "").strip()
        if not saved_hash:
            issues.append(f"receipt {index} is missing receipt_hash")
        else:
            expected_hash = route_receipt_compute_hash(receipt)
            if saved_hash != expected_hash:
                issues.append(f"receipt {index} receipt_hash does not match payload")
        if previous_hash is not None and previous_receipt_hash != previous_hash:
            issues.append(
                f"receipt {index} previous_receipt_hash does not link to receipt {index - 1}"
            )
        previous_hash = saved_hash
    return issues


def _route_receipt_remote_path(target_row: dict[str, Any]) -> str:
    owner = str(target_row.get("owner_tui") or "")
    sink = str(target_row.get("route_receipt_sink") or "").strip()
    if sink:
        return sink
    return str(DEFAULT_ROUTE_RECEIPT_DIR / f"{owner}.jsonl")


def _route_receipt_remote_source(
    target_row: dict[str, Any],
) -> dict[str, str] | None:
    owner = str(target_row.get("owner_tui") or "").strip()
    host_name = ROUTE_RECEIPT_REMOTE_OWNER_HOSTS.get(owner, "").strip()
    if not owner or not host_name:
        return None
    ssh_target = ROUTE_RECEIPT_REMOTE_HOSTS.get(host_name, "").strip()
    if not ssh_target:
        return None
    return {
        "owner_tui": owner,
        "host": host_name,
        "ssh_target": ssh_target,
        "remote_path": _route_receipt_remote_path(target_row),
    }


def _ssh_cat_remote_file(
    ssh_target: str, remote_path: str
) -> subprocess.CompletedProcess:
    quoted_path = shlex.quote(remote_path)
    return subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={ROUTE_RECEIPT_REMOTE_CONNECT_TIMEOUT_SECONDS}",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "StrictHostKeyChecking=accept-new",
            ssh_target,
            f"test -f {quoted_path} && cat {quoted_path}",
        ],
        check=False,
        capture_output=True,
    )


def harvest_route_receipts(
    flow_plan: dict[str, Any],
    *,
    receipt_dir: Path = DEFAULT_ROUTE_RECEIPT_DIR,
    owners: tuple[str, ...] = (),
) -> dict[str, Any]:
    if flow_plan.get("schema") != "norman.tui-flow-canary-plan.v1":
        raise ValueError("flow plan is not a TUI flow canary plan")

    owner_filter = {owner.strip() for owner in owners if owner.strip()}
    rows: list[dict[str, Any]] = []
    for target in flow_plan.get("targets", []):
        if not isinstance(target, dict):
            continue
        owner = str(target.get("owner_tui") or "").strip()
        if owner_filter and owner not in owner_filter:
            continue
        local_path = _route_receipt_path(target, receipt_dir)
        source = _route_receipt_remote_source(target)
        if source is None:
            rows.append(
                {
                    "owner_tui": owner,
                    "status": "skipped",
                    "reason": "no configured remote receipt source",
                    "local_path": str(local_path),
                }
            )
            continue

        result = _ssh_cat_remote_file(source["ssh_target"], source["remote_path"])
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        if result.returncode == 0:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(result.stdout)
            line_count = len(
                [line for line in result.stdout.splitlines() if line.strip()]
            )
            rows.append(
                {
                    **source,
                    "status": "copied",
                    "local_path": str(local_path),
                    "bytes": len(result.stdout),
                    "line_count": line_count,
                }
            )
        elif result.returncode == 1 and not result.stdout and not stderr:
            rows.append(
                {
                    **source,
                    "status": "missing",
                    "local_path": str(local_path),
                    "bytes": 0,
                    "line_count": 0,
                    "reason": "remote receipt sink is missing",
                }
            )
        else:
            rows.append(
                {
                    **source,
                    "status": "error",
                    "local_path": str(local_path),
                    "bytes": 0,
                    "line_count": 0,
                    "reason": stderr or f"ssh exited {result.returncode}",
                }
            )

    copied_count = sum(1 for row in rows if row.get("status") == "copied")
    return {
        "schema": "norman.tui-route-receipt-harvest.v1",
        "generated_at": int(time.time()),
        "source_schema": flow_plan.get("schema"),
        "dry_run_only": False,
        "live_state_mutated": False,
        "description": (
            "Harvests existing remote route receipt JSONL files into the local "
            "benchmark directory. It does not restart services, enqueue prompts, "
            "change routes, or write back to remote hosts."
        ),
        "summary": {
            "target_count": len(rows),
            "copied_count": copied_count,
            "missing_count": sum(1 for row in rows if row.get("status") == "missing"),
            "error_count": sum(1 for row in rows if row.get("status") == "error"),
            "skipped_count": sum(1 for row in rows if row.get("status") == "skipped"),
            "line_count": sum(_coerce_int(row.get("line_count")) for row in rows),
            "byte_count": sum(_coerce_int(row.get("bytes")) for row in rows),
        },
        "targets": rows,
    }


def render_route_receipt_harvest_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# TUI Route Receipt Harvest",
        "",
        "Copies existing remote route receipt JSONL files into the local benchmark directory.",
        "",
        "## Summary",
        "",
        f"- Targets: {summary.get('target_count')}",
        f"- Copied: {summary.get('copied_count')}",
        f"- Missing: {summary.get('missing_count')}",
        f"- Errors: {summary.get('error_count')}",
        f"- Skipped: {summary.get('skipped_count')}",
        f"- Lines: {summary.get('line_count')}",
        f"- Bytes: {summary.get('byte_count')}",
        f"- Live state mutated: {report.get('live_state_mutated')}",
        "",
        "## Targets",
        "",
        "| Owner TUI | Status | Host | Remote path | Local path | Lines | Reason |",
        "|---|---|---|---|---|---:|---|",
    ]
    for row in report.get("targets", []):
        lines.append(
            "| {owner} | {status} | {host} | {remote} | {local} | {lines} | {reason} |".format(
                owner=_cell(row.get("owner_tui")),
                status=_cell(row.get("status")),
                host=_cell(row.get("host", "")),
                remote=_cell(row.get("remote_path", "")),
                local=_cell(row.get("local_path", "")),
                lines=_coerce_int(row.get("line_count")),
                reason=_cell(row.get("reason", "")),
            )
        )
    return "\n".join(lines) + "\n"


def _receipt_validator_passed(receipt: dict[str, Any]) -> bool:
    gate = str(receipt.get("validator_gate") or "").strip().lower()
    return gate in {"pass", "passed", "accept", "accepted", "ok", "green"} and (
        _nonempty_string(receipt.get("independent_validator_id"))
        and _nonempty_sequence(receipt.get("evidence_refs"))
    )


def _receipt_manual_override(receipt: dict[str, Any]) -> bool:
    if _safe_bool(receipt.get("manual_override")):
        return True
    outcome = str(receipt.get("outcome") or "").strip().lower()
    return "manual" in outcome and "override" in outcome


def _receipt_fallback_used(receipt: dict[str, Any]) -> bool:
    return not _blankish(receipt.get("fallback_used"))


def _receipt_boundary_violation(
    receipt: dict[str, Any], blocked_actions: list[str]
) -> bool:
    if _safe_bool(receipt.get("boundary_violation")):
        return True
    if _safe_bool(receipt.get("live_write_attempted")):
        return True
    outcome = str(receipt.get("outcome") or "").strip().lower()
    if "boundary" in outcome or "violation" in outcome:
        return True
    requested = str(receipt.get("requested_action") or "").strip().lower()
    return any(action.lower() in requested for action in blocked_actions if action)


def _receipt_cost_savings(receipts: list[dict[str, Any]]) -> tuple[float | None, int]:
    estimated_total = 0.0
    baseline_total = 0.0
    sample_count = 0
    for receipt in receipts:
        estimated = _safe_float(
            receipt.get("workflow_cost_usd") or receipt.get("estimated_cost_usd")
        )
        baseline = _safe_float(
            receipt.get("counterfactual_workflow_cost_usd")
            or receipt.get("baseline_all_5_5_cost_usd")
        )
        if estimated is None or baseline is None or baseline <= 0:
            continue
        estimated_total += max(0.0, estimated)
        baseline_total += baseline
        sample_count += 1
    if sample_count == 0 or baseline_total <= 0:
        return None, sample_count
    return round(1.0 - (estimated_total / baseline_total), 4), sample_count


def _receipt_created_at_seconds(receipt: dict[str, Any]) -> int | None:
    raw = receipt.get("created_at")
    if isinstance(raw, int | float):
        return int(raw)
    clean = str(raw or "").strip()
    if not clean:
        return None
    if clean.isdigit():
        return int(clean)
    try:
        from datetime import datetime

        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(parsed.timestamp())


def _receipt_evidence_span_seconds(receipts: list[dict[str, Any]]) -> int:
    times = [
        value
        for value in (_receipt_created_at_seconds(receipt) for receipt in receipts)
        if value is not None
    ]
    if len(times) < 2:
        return 0
    return max(times) - min(times)


def _receipt_task_class(receipt: dict[str, Any]) -> str:
    for field in (
        "task_class",
        "operator_intent_class",
        "requested_action",
        "benchmark_skill_id",
    ):
        value = str(receipt.get(field) or "").strip().lower()
        if value:
            return value
    return "unknown"


def _task_class_counts(receipts: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for receipt in receipts:
        label = _receipt_task_class(receipt)
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def _task_class_quota_passed(counts: dict[str, int]) -> bool:
    qualified = [
        label
        for label, count in counts.items()
        if label != "unknown" and count >= MIN_CUTOVER_TASK_CLASS_QUOTA
    ]
    return len(qualified) >= MIN_CUTOVER_TASK_CLASS_COUNT


def _receipt_visible_complete(receipt: dict[str, Any]) -> bool:
    shape = str(receipt.get("output_shape") or "").strip().lower()
    return (
        shape == "complete"
        and _safe_bool(receipt.get("visible_delivery_passed"))
        and _nonempty_string(receipt.get("visible_response_ref"))
    )


def _receipt_policy_fresh(receipt: dict[str, Any]) -> bool:
    state = (
        str(
            receipt.get("policy_lifecycle_state")
            or receipt.get("route_policy_lifecycle")
            or ""
        )
        .strip()
        .lower()
    )
    if (
        state in {"valid", "expiring_soon"}
        and _nonempty_string(receipt.get("policy_id"))
        and _nonempty_string(receipt.get("policy_hash"))
    ):
        return True
    freshness = str(receipt.get("policy_freshness") or "").strip().lower()
    return freshness in {"fresh", "valid"}


def _receipt_hidden_cloud(receipt: dict[str, Any]) -> bool:
    if _safe_bool(receipt.get("cloud_proxy")):
        return True
    bucket = str(receipt.get("usage_bucket") or "").strip().lower()
    provider = (
        str(
            receipt.get("observed_provider")
            or receipt.get("selected_provider")
            or receipt.get("provider")
            or ""
        )
        .strip()
        .lower()
    )
    cloudish = any(
        token in f"{bucket} {provider}"
        for token in ("openai", "bedrock", "cloud_llm", "amazon")
    )
    if not cloudish:
        return False
    return not _safe_bool(receipt.get("cloud_accounted"))


def route_receipt_strict_issues(
    receipt: dict[str, Any],
    *,
    index: int,
    required_fields: list[str],
    blocked_actions: list[str],
) -> list[str]:
    issues: list[str] = []
    for field in required_fields:
        if field not in receipt:
            issues.append(f"receipt {index} missing required field: {field}")
    for field in ROUTE_RECEIPT_STRICT_NONEMPTY_FIELDS:
        if not _nonempty_string(receipt.get(field)):
            issues.append(f"receipt {index} has blank trusted field: {field}")
    if not _nonempty_sequence(receipt.get("evidence_refs")):
        issues.append(f"receipt {index} has no evidence_refs")
    for field in (
        "synthetic",
        "cloud_accounted",
        "visible_delivery_passed",
        "manual_override",
        "boundary_violation",
        "live_write_attempted",
    ):
        if not isinstance(receipt.get(field), bool):
            issues.append(f"receipt {index} {field} is not a boolean")
    if _safe_bool(receipt.get("synthetic")):
        issues.append(f"receipt {index} is synthetic")
    source = str(receipt.get("receipt_source") or "").strip()
    if source not in {
        "live_shadow_canary",
        "live_operator",
        "live_acceptance",
        "live_operator_cohort",
    }:
        issues.append(f"receipt {index} receipt_source is not live evidence")
    if _receipt_created_at_seconds(receipt) is None:
        issues.append(f"receipt {index} has invalid created_at")
    if _coerce_int(receipt.get("receipt_sequence")) <= 0:
        issues.append(f"receipt {index} has invalid receipt_sequence")
    algorithm = str(receipt.get("receipt_signature_algorithm") or "").strip().lower()
    if algorithm not in RECEIPT_SIGNATURE_ALGORITHMS:
        issues.append(f"receipt {index} uses unsupported signature algorithm")
    if not _hex_digest(receipt.get("segment_root")):
        issues.append(f"receipt {index} has invalid segment_root")
    if not _receipt_validator_passed(receipt):
        issues.append(f"receipt {index} lacks independent validator pass evidence")
    if not _receipt_visible_complete(receipt):
        issues.append(f"receipt {index} lacks visible completion proof")
    if not _receipt_policy_fresh(receipt):
        issues.append(f"receipt {index} lacks fresh policy identity")
    if _receipt_hidden_cloud(receipt):
        issues.append(f"receipt {index} has hidden cloud/proxy usage")
    if _receipt_boundary_violation(receipt, blocked_actions):
        issues.append(f"receipt {index} has boundary violation evidence")
    selected_provider = str(receipt.get("selected_provider") or "").strip()
    observed_provider = str(receipt.get("observed_provider") or "").strip()
    selected_model = str(receipt.get("selected_model") or "").strip()
    observed_model = str(receipt.get("observed_model") or "").strip()
    if (
        selected_provider
        and observed_provider
        and selected_provider != observed_provider
    ):
        issues.append(f"receipt {index} selected/observed provider mismatch")
    if selected_model and observed_model and selected_model != observed_model:
        issues.append(f"receipt {index} selected/observed model mismatch")
    usage_bucket = str(receipt.get("usage_bucket") or "").strip().lower()
    if usage_bucket in {"offline_local", "local", "norllama"} and not _nonempty_string(
        receipt.get("observed_worker")
    ):
        issues.append(f"receipt {index} local route lacks observed_worker")
    if _safe_bool(receipt.get("operator_approval_required")):
        if not _nonempty_string(receipt.get("approval_id")):
            issues.append(f"receipt {index} requires approval without approval_id")
        if not _nonempty_string(receipt.get("pending_action_digest")):
            issues.append(
                f"receipt {index} requires approval without pending_action_digest"
            )
    return issues


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * 0.95)))
    return ordered[index]


def _receipt_is_5_4_verifier(receipt: dict[str, Any]) -> bool:
    tier = str(receipt.get("selected_model_tier") or "").strip().lower()
    role = str(receipt.get("allowed_role") or "").strip().lower()
    return "5_4" in tier or role == "verifier"


def _receipt_has_5_4_verifier_decision(receipt: dict[str, Any]) -> bool:
    gate = str(receipt.get("validator_gate") or "").strip().lower()
    return _receipt_is_5_4_verifier(receipt) and gate in {
        "pass",
        "passed",
        "accept",
        "accepted",
        "ok",
        "green",
        "fail",
        "failed",
        "reject",
        "rejected",
        "red",
    }


def _receipt_matches_launch_gate(
    receipt: dict[str, Any], target_row: dict[str, Any]
) -> tuple[bool, str]:
    launch_gate = str(target_row.get("launch_gate") or "").strip()
    tier = str(receipt.get("selected_model_tier") or "").strip().lower()
    role = str(receipt.get("allowed_role") or "").strip().lower()
    if launch_gate == "ready_for_shadow_route_receipts":
        if role != "worker_draft":
            return False, "expected worker_draft role for wave-1 route receipts"
        if any(token in tier for token in ("5_4", "5_5")):
            return False, "wave-1 route receipts drifted onto verifier/final tiers"
        return True, ""
    if launch_gate == "ready_for_5_4_shadow_verifier":
        if _receipt_is_5_4_verifier(receipt):
            return True, ""
        return False, "wave-2 receipts must stay on the 5.4 verifier lane"
    return True, ""


def _target_promotion_contract(target_row: dict[str, Any]) -> dict[str, Any]:
    launch_gate = str(target_row.get("launch_gate") or "").strip()
    if launch_gate == "ready_for_shadow_route_receipts":
        return {
            "phase": "wave_1_limited_cutover",
            "promotion_candidate": True,
            "cutover_candidate": True,
            "min_receipts": MIN_CUTOVER_ROUTE_RECEIPTS,
            "receipt_label": "route receipts",
            "ready_gate": "ready_for_limited_guarded_cutover",
            "ready_next_action": (
                "request operator approval for a limited guarded cutover"
            ),
            "count_next_action": (
                "collect {remaining} more live shadow route receipts for {owner}"
            ),
            "require_validator_pass_rate": True,
            "require_cost_savings": True,
            "require_5_4_verifier_receipts": False,
            "require_5_4_verifier_decisions": False,
            "hold_reason": "",
            "hold_next_action": "",
        }
    if launch_gate == "ready_for_5_4_shadow_verifier":
        return {
            "phase": "wave_2_5_4_shadow_verifier",
            "promotion_candidate": True,
            "cutover_candidate": False,
            "min_receipts": MIN_CUTOVER_ROUTE_RECEIPTS,
            "receipt_label": "shadow verifier receipts",
            "ready_gate": "ready_for_5_4_verified_shadow_promotion",
            "ready_next_action": (
                "keep the lane in operator-visible shadow with the 5.4 verifier as the acceptance gate"
            ),
            "count_next_action": (
                "collect {remaining} more 5.4 shadow verifier receipts for {owner}"
            ),
            "require_validator_pass_rate": False,
            "require_cost_savings": False,
            "require_5_4_verifier_receipts": True,
            "require_5_4_verifier_decisions": True,
            "hold_reason": "",
            "hold_next_action": "",
        }
    if launch_gate == "hold_until_validator_receipts":
        return {
            "phase": "wave_3_validator_gap_hold",
            "promotion_candidate": False,
            "cutover_candidate": False,
            "min_receipts": 0,
            "receipt_label": "validator-backed receipts",
            "ready_gate": "hold_until_validator_receipts",
            "ready_next_action": "",
            "count_next_action": "",
            "require_validator_pass_rate": False,
            "require_cost_savings": False,
            "require_5_4_verifier_receipts": False,
            "require_5_4_verifier_decisions": False,
            "hold_reason": "target is still in validator-gap shadow hold",
            "hold_next_action": (
                "add deterministic validators or promote the workflow into the 5.4 verifier lane before capture"
            ),
        }
    return {
        "phase": "wave_4_final_authority_hold",
        "promotion_candidate": False,
        "cutover_candidate": False,
        "min_receipts": 0,
        "receipt_label": "final-authority dry runs",
        "ready_gate": "hold_final_authority",
        "ready_next_action": "",
        "count_next_action": "",
        "require_validator_pass_rate": False,
        "require_cost_savings": False,
        "require_5_4_verifier_receipts": False,
        "require_5_4_verifier_decisions": False,
        "hold_reason": "target remains final-authority dry-run only",
        "hold_next_action": (
            "keep the workflow in dry-run/final-authority hold; do not promote without an explicit operator-approved contract change"
        ),
    }


def _target_cutover_metrics(
    target_row: dict[str, Any],
    *,
    receipt_dir: Path,
    receipt_contract: dict[str, Any],
) -> dict[str, Any]:
    path = _route_receipt_path(target_row, receipt_dir)
    receipts, load_errors = load_route_receipts(path)
    chain_issues = route_receipt_chain_issues(receipts)
    required_fields = list(receipt_contract.get("required_fields") or [])
    blocked_actions = list(target_row.get("blocked_actions") or [])
    missing_required_count = sum(
        1
        for receipt in receipts
        if any(field not in receipt for field in required_fields)
    )
    strict_issue_lists = [
        route_receipt_strict_issues(
            receipt,
            index=index,
            required_fields=required_fields,
            blocked_actions=blocked_actions,
        )
        for index, receipt in enumerate(receipts, 1)
    ]
    strict_issue_count = sum(len(issues) for issues in strict_issue_lists)
    strict_invalid_receipt_count = sum(1 for issues in strict_issue_lists if issues)
    strict_issue_examples = [
        issue for issues in strict_issue_lists for issue in issues[:2]
    ][:8]
    validator_pass_count = sum(
        1 for item in receipts if _receipt_validator_passed(item)
    )
    fallback_count = sum(1 for item in receipts if _receipt_fallback_used(item))
    manual_override_count = sum(
        1 for item in receipts if _receipt_manual_override(item)
    )
    boundary_violation_count = sum(
        1 for item in receipts if _receipt_boundary_violation(item, blocked_actions)
    )
    synthetic_receipt_count = sum(
        1 for item in receipts if _safe_bool(item.get("synthetic"))
    )
    verifier_receipt_count = sum(
        1 for item in receipts if _receipt_is_5_4_verifier(item)
    )
    route_match_results = [
        _receipt_matches_launch_gate(item, target_row) for item in receipts
    ]
    route_match_count = sum(1 for matched, _reason in route_match_results if matched)
    route_drift_reasons = [
        reason for matched, reason in route_match_results if not matched and reason
    ]
    route_drift_count = len(route_drift_reasons)
    verifier_decision_count = sum(
        1 for item in receipts if _receipt_has_5_4_verifier_decision(item)
    )
    operator_approval_route_count = sum(
        1 for item in receipts if _safe_bool(item.get("operator_approval_required"))
    )
    final_authority_route_count = sum(
        1 for item in receipts if _safe_bool(item.get("final_authority_required"))
    )
    live_write_attempt_count = sum(
        1 for item in receipts if _safe_bool(item.get("live_write_attempted"))
    )
    receipt_count = len(receipts)
    evidence_span_seconds = _receipt_evidence_span_seconds(receipts)
    task_class_counts = _task_class_counts(receipts)
    task_class_quota_passed = _task_class_quota_passed(task_class_counts)
    visible_completion_count = sum(
        1 for item in receipts if _receipt_visible_complete(item)
    )
    policy_fresh_count = sum(1 for item in receipts if _receipt_policy_fresh(item))
    hidden_cloud_count = sum(1 for item in receipts if _receipt_hidden_cloud(item))
    latency_values = [
        value
        for value in (_coerce_int(item.get("latency_ms")) for item in receipts)
        if value > 0
    ]
    p95_latency_ms = _p95(latency_values)
    validator_pass_rate = (
        round(validator_pass_count / receipt_count, 4) if receipt_count else 0.0
    )
    fallback_rate = round(fallback_count / receipt_count, 4) if receipt_count else 0.0
    manual_override_rate = (
        round(manual_override_count / receipt_count, 4) if receipt_count else 0.0
    )
    cost_savings, cost_sample_count = _receipt_cost_savings(receipts)
    contract = _target_promotion_contract(target_row)
    min_receipts = _coerce_int(contract.get("min_receipts"))

    blockers: list[str] = []
    hold_reason = str(contract.get("hold_reason") or "").strip()
    if hold_reason:
        blockers.append(hold_reason)
    if min_receipts > 0 and receipt_count < min_receipts:
        blockers.append(
            f"needs at least {min_receipts} {contract.get('receipt_label')}; found {receipt_count}"
        )
    if min_receipts > 0 and evidence_span_seconds < MIN_CUTOVER_OBSERVATION_SECONDS:
        blockers.append(
            "receipt evidence must span at least "
            f"{MIN_CUTOVER_OBSERVATION_SECONDS // 3600} hours; "
            f"found {round(evidence_span_seconds / 3600, 2)} hours"
        )
    if min_receipts > 0 and not task_class_quota_passed:
        blockers.append(
            "receipt cohort lacks representative task-class quotas "
            f"({MIN_CUTOVER_TASK_CLASS_COUNT} classes with "
            f"{MIN_CUTOVER_TASK_CLASS_QUOTA}+ receipts required)"
        )
    if load_errors:
        blockers.append("route receipt sink has malformed or unreadable records")
    if chain_issues:
        blockers.append(f"route receipt hash chain has {len(chain_issues)} issue(s)")
    if missing_required_count:
        blockers.append(
            f"{missing_required_count} route receipts are missing required fields"
        )
    if strict_issue_count:
        blockers.append(
            f"{strict_invalid_receipt_count} route receipts failed strict evidence validation"
        )
    if (
        contract.get("require_validator_pass_rate")
        and validator_pass_rate < MIN_CUTOVER_VALIDATOR_PASS_RATE
    ):
        blockers.append(
            f"validator pass rate {validator_pass_rate:.1%} is below {MIN_CUTOVER_VALIDATOR_PASS_RATE:.0%}"
        )
    if manual_override_rate > MAX_CUTOVER_MANUAL_OVERRIDE_RATE:
        blockers.append(
            f"manual override rate {manual_override_rate:.1%} is above {MAX_CUTOVER_MANUAL_OVERRIDE_RATE:.0%}"
        )
    if fallback_rate > MAX_CUTOVER_FALLBACK_RATE:
        blockers.append(
            f"fallback rate {fallback_rate:.1%} is above {MAX_CUTOVER_FALLBACK_RATE:.0%}"
        )
    if boundary_violation_count:
        blockers.append(f"{boundary_violation_count} boundary violations found")
    if synthetic_receipt_count:
        blockers.append(f"{synthetic_receipt_count} synthetic receipts found")
    if live_write_attempt_count:
        blockers.append(f"{live_write_attempt_count} live-write attempts found")
    if visible_completion_count < receipt_count:
        blockers.append(
            f"{receipt_count - visible_completion_count} receipts lack visible complete output proof"
        )
    if policy_fresh_count < receipt_count:
        blockers.append(
            f"{receipt_count - policy_fresh_count} receipts lack fresh policy identity"
        )
    if hidden_cloud_count:
        blockers.append(f"{hidden_cloud_count} hidden cloud/proxy usages found")
    if p95_latency_ms > MAX_CUTOVER_P95_LATENCY_MS:
        blockers.append(
            f"p95 latency {p95_latency_ms}ms exceeds {MAX_CUTOVER_P95_LATENCY_MS}ms"
        )
    if route_drift_count:
        blockers.append(
            f"{route_drift_count} receipts drifted from {target_row.get('flow_mode')}"
        )
    if operator_approval_route_count:
        blockers.append(
            f"{operator_approval_route_count} routes required operator approval"
        )
    if final_authority_route_count:
        blockers.append(
            f"{final_authority_route_count} routes required final authority"
        )
    if (
        contract.get("require_5_4_verifier_receipts")
        and verifier_receipt_count < receipt_count
    ):
        blockers.append(
            f"{receipt_count - verifier_receipt_count} receipts are missing 5.4 verifier routing"
        )
    if (
        contract.get("require_5_4_verifier_decisions")
        and verifier_decision_count < receipt_count
    ):
        blockers.append(
            f"{receipt_count - verifier_decision_count} receipts are missing explicit 5.4 verifier accept/reject evidence"
        )
    if contract.get("require_cost_savings") and cost_sample_count < receipt_count:
        blockers.append(
            "missing full workflow counterfactual cost evidence on "
            f"{receipt_count - cost_sample_count} receipts"
        )
    elif contract.get("require_cost_savings") and cost_savings is None:
        blockers.append("missing full workflow counterfactual cost evidence")
    elif (
        contract.get("require_cost_savings") and cost_savings < MIN_CUTOVER_COST_SAVINGS
    ):
        blockers.append(
            f"cost savings {cost_savings:.1%} is below {MIN_CUTOVER_COST_SAVINGS:.0%}"
        )

    next_actions: list[str] = []
    hold_next_action = str(contract.get("hold_next_action") or "").strip()
    if hold_next_action:
        next_actions.append(hold_next_action)
    elif min_receipts > 0 and receipt_count < min_receipts:
        remaining = min_receipts - receipt_count
        next_actions.append(
            str(contract.get("count_next_action") or "").format(
                remaining=remaining,
                owner=target_row.get("owner_tui"),
            )
        )
    if final_authority_route_count:
        next_actions.append(
            "exercise bounded worker/draft canary prompts; current receipts are safety holds, not savings evidence"
        )
    if route_drift_count:
        next_actions.append(
            "keep the lane in observe/canary mode until the emitted route receipts match the intended canary tier"
        )
    if operator_approval_route_count:
        next_actions.append(
            "exclude approval-required prompts from the money-saving canary set"
        )
    if (
        contract.get("require_5_4_verifier_receipts")
        and verifier_receipt_count < receipt_count
    ):
        next_actions.append(
            "keep wave-2 samples on the 5.4 verifier lane; exclude lower-only or 5.5 final-authority receipts from the promotion set"
        )
    if (
        contract.get("require_5_4_verifier_decisions")
        and verifier_decision_count < receipt_count
    ):
        next_actions.append(
            "ensure the 5.4 verifier records explicit pass/fail decisions on every sampled workflow"
        )
    if contract.get("require_cost_savings") and cost_savings is None:
        next_actions.append(
            "ensure each receipt includes workflow_cost_usd and counterfactual_workflow_cost_usd"
        )
    elif (
        contract.get("require_cost_savings") and cost_savings < MIN_CUTOVER_COST_SAVINGS
    ):
        next_actions.append(
            "collect receipts that route below final authority before considering cutover"
        )
    if boundary_violation_count or live_write_attempt_count:
        next_actions.append("reset the canary after removing unsafe live-write traffic")
    if chain_issues:
        next_actions.append(
            "restart promotion evidence after fixing route receipt hashing"
        )
    if not next_actions and not blockers:
        next_actions.append(str(contract.get("ready_next_action") or ""))

    promotion_ready = bool(contract.get("promotion_candidate")) and not blockers
    cutover_ready = bool(contract.get("cutover_candidate")) and promotion_ready

    return {
        "owner_tui": target_row.get("owner_tui"),
        "wave": target_row.get("wave"),
        "promotion_phase": contract.get("phase"),
        "launch_gate": target_row.get("launch_gate"),
        "receipt_path": str(path),
        "promotion_gate": contract.get("ready_gate")
        if promotion_ready
        else "not_ready",
        "promotion_ready": promotion_ready,
        "cutover_gate": (
            "ready_for_limited_guarded_cutover" if cutover_ready else "not_ready"
        ),
        "cutover_ready": cutover_ready,
        "blockers": blockers,
        "next_actions": next_actions,
        "load_errors": load_errors,
        "chain_issues": chain_issues,
        "metrics": {
            "receipt_count": receipt_count,
            "minimum_receipts_required": min_receipts,
            "minimum_observation_seconds_required": MIN_CUTOVER_OBSERVATION_SECONDS,
            "evidence_span_seconds": evidence_span_seconds,
            "task_class_counts": task_class_counts,
            "task_class_quota_passed": task_class_quota_passed,
            "visible_completion_count": visible_completion_count,
            "policy_fresh_count": policy_fresh_count,
            "hidden_cloud_count": hidden_cloud_count,
            "p95_latency_ms": p95_latency_ms,
            "strict_invalid_receipt_count": strict_invalid_receipt_count,
            "strict_issue_count": strict_issue_count,
            "strict_issue_examples": strict_issue_examples,
            "missing_required_count": missing_required_count,
            "chain_issue_count": len(chain_issues),
            "validator_pass_rate": validator_pass_rate,
            "manual_override_rate": manual_override_rate,
            "fallback_rate": fallback_rate,
            "boundary_violation_count": boundary_violation_count,
            "synthetic_receipt_count": synthetic_receipt_count,
            "live_write_attempt_count": live_write_attempt_count,
            "route_match_count": route_match_count,
            "route_drift_count": route_drift_count,
            "route_drift_examples": route_drift_reasons[:3],
            "verifier_receipt_count": verifier_receipt_count,
            "verifier_decision_count": verifier_decision_count,
            "operator_approval_route_count": operator_approval_route_count,
            "final_authority_route_count": final_authority_route_count,
            "cost_savings_vs_all_5_5": cost_savings,
            "cost_sample_count": cost_sample_count,
        },
    }


def _historic_route_benchmark_gate(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "configured": False,
            "gate": "not_configured",
            "path": "",
            "blockers": [],
        }
    blockers: list[str] = []
    if not path.exists():
        return {
            "configured": True,
            "gate": "hold",
            "path": str(path),
            "blockers": [f"missing historic route benchmark: {path}"],
        }
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "configured": True,
            "gate": "hold",
            "path": str(path),
            "blockers": [f"malformed historic route benchmark: {exc.msg}"],
        }
    if not isinstance(report, dict):
        return {
            "configured": True,
            "gate": "hold",
            "path": str(path),
            "blockers": ["historic route benchmark is not a JSON object"],
        }
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    source = report.get("source") if isinstance(report.get("source"), dict) else {}
    if report.get("schema") != "norman.historic-shadow-planner-route-benchmark.v1":
        blockers.append("historic route benchmark schema mismatch")
    if summary.get("planner_shadow_cutover_gate") != "pass":
        blockers.append(
            f"historic route benchmark gate is {summary.get('planner_shadow_cutover_gate') or 'missing'}"
        )
    policy_version = str(summary.get("policy_version") or "")
    if policy_version != REQUIRED_HISTORIC_ROUTE_POLICY_VERSION:
        blockers.append(
            "historic route benchmark policy version is "
            f"{policy_version or 'missing'}; expected {REQUIRED_HISTORIC_ROUTE_POLICY_VERSION}"
        )
    accuracy_fail_count = _coerce_int(summary.get("accuracy_gate_fail_count"))
    if accuracy_fail_count:
        blockers.append(
            f"historic route benchmark has {accuracy_fail_count} accuracy gate failures"
        )
    policy_fail_count = _coerce_int(summary.get("routing_policy_compliance_fail_count"))
    if policy_fail_count:
        blockers.append(
            f"historic route benchmark has {policy_fail_count} routing policy compliance failures"
        )
    planner_action_policy_version = str(
        summary.get("planner_action_policy_version") or ""
    )
    if (
        planner_action_policy_version
        != REQUIRED_HISTORIC_ROUTE_PLANNER_ACTION_POLICY_VERSION
    ):
        blockers.append(
            "historic route benchmark planner action policy version is "
            f"{planner_action_policy_version or 'missing'}; expected "
            f"{REQUIRED_HISTORIC_ROUTE_PLANNER_ACTION_POLICY_VERSION}"
        )
    planner_action_case_count = _coerce_int(summary.get("planner_action_case_count"))
    if planner_action_case_count <= 0:
        blockers.append("historic route benchmark has no planner-action cases")
    planner_action_fail_count = _coerce_int(summary.get("planner_action_fail_count"))
    if planner_action_fail_count:
        blockers.append(
            "historic route benchmark has "
            f"{planner_action_fail_count} planner-action failures"
        )
    planner_action_score = _safe_float(summary.get("median_planner_action_score"))
    if planner_action_score is None:
        blockers.append(
            "historic route benchmark is missing planner-action score evidence"
        )
    elif planner_action_score < MIN_HISTORIC_ROUTE_PLANNER_ACTION_SCORE:
        blockers.append(
            "historic route benchmark planner-action score "
            f"{planner_action_score:.1%} is below "
            f"{MIN_HISTORIC_ROUTE_PLANNER_ACTION_SCORE:.0%}"
        )
    lower_model_case_count = _coerce_int(summary.get("lower_model_case_count"))
    if lower_model_case_count <= 0:
        blockers.append("historic route benchmark has no lower-model eligible cases")
    savings = _safe_float(summary.get("savings_vs_all_bedrock_5_5_xhigh"))
    if savings is None:
        blockers.append("historic route benchmark is missing savings evidence")
    elif savings < MIN_HISTORIC_ROUTE_BENCHMARK_SAVINGS:
        blockers.append(
            f"historic route benchmark savings {savings:.1%} is below {MIN_HISTORIC_ROUTE_BENCHMARK_SAVINGS:.0%}"
        )
    five_five_share = _safe_float(summary.get("median_five_five_token_share_vs_raw"))
    if five_five_share is None:
        blockers.append("historic route benchmark is missing 5.5 token share evidence")
    elif five_five_share > MAX_HISTORIC_ROUTE_BENCHMARK_FIVE_FIVE_SHARE:
        blockers.append(
            f"historic route benchmark median 5.5 token share {five_five_share:.1%} exceeds {MAX_HISTORIC_ROUTE_BENCHMARK_FIVE_FIVE_SHARE:.0%}"
        )
    case_count = _coerce_int(summary.get("case_count"))
    if case_count <= 0:
        blockers.append("historic route benchmark has no cases")
    split_counts = (
        summary.get("split_counts")
        if isinstance(summary.get("split_counts"), dict)
        else {}
    )
    holdout_count = _coerce_int(split_counts.get("holdout"))
    if holdout_count <= 0:
        blockers.append("historic route benchmark has no holdout cases")
    return {
        "configured": True,
        "gate": "pass" if not blockers else "hold",
        "path": str(path),
        "blockers": blockers,
        "schema": report.get("schema"),
        "case_count": case_count,
        "holdout_count": holdout_count,
        "policy_version": policy_version,
        "accuracy_gate_pass_count": _coerce_int(
            summary.get("accuracy_gate_pass_count")
        ),
        "accuracy_gate_fail_count": accuracy_fail_count,
        "routing_policy_compliance_pass_count": _coerce_int(
            summary.get("routing_policy_compliance_pass_count")
        ),
        "routing_policy_compliance_fail_count": policy_fail_count,
        "planner_action_policy_version": planner_action_policy_version,
        "planner_action_case_count": planner_action_case_count,
        "planner_action_fail_count": planner_action_fail_count,
        "median_planner_action_score": planner_action_score,
        "lower_model_case_count": lower_model_case_count,
        "savings_vs_all_bedrock_5_5_xhigh": savings,
        "median_raw_context_compression_rate": summary.get(
            "median_raw_context_compression_rate"
        ),
        "median_five_five_token_share_vs_raw": five_five_share,
        "source_turn_count": source.get("source_turn_count"),
        "source_evidence_turn_count": source.get("source_evidence_turn_count"),
    }


def _route_policy_lifecycle_gate(
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    try:
        contract = dict(policy or route_policy_contract())
        lifecycle = route_policy_lifecycle(contract)
    except Exception as exc:
        return {
            "configured": True,
            "gate": "hold",
            "blockers": [
                f"route policy lifecycle check failed: {type(exc).__name__}: {exc}"
            ],
            "warnings": [],
            "lifecycle": {
                "state": "refresh_failed",
                "default_route_allowed": False,
                "degraded": True,
            },
        }
    state = str(lifecycle.get("state") or "unknown")
    if not bool(lifecycle.get("default_route_allowed")):
        blockers.append(
            "route policy lifecycle blocks default routing: "
            f"{state}; refresh the compiled policy artifact before cutover"
        )
    elif state == "expiring_soon":
        warnings.append(
            "route policy expires soon; refresh before broadening cutover scope"
        )
    return {
        "configured": True,
        "gate": "pass" if not blockers else "hold",
        "blockers": blockers,
        "warnings": warnings,
        "lifecycle": lifecycle,
    }


def build_cutover_readiness_report(
    flow_plan: dict[str, Any],
    *,
    receipt_dir: Path = DEFAULT_ROUTE_RECEIPT_DIR,
    historic_route_benchmark_path: Path | None = None,
    route_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if flow_plan.get("schema") != "norman.tui-flow-canary-plan.v1":
        raise ValueError("flow plan is not a TUI flow canary plan")
    receipt_contract = (
        flow_plan.get("route_receipt_contract")
        if isinstance(flow_plan.get("route_receipt_contract"), dict)
        else {}
    )
    targets = [
        _target_cutover_metrics(
            target,
            receipt_dir=receipt_dir,
            receipt_contract=receipt_contract,
        )
        for target in flow_plan.get("targets", [])
        if isinstance(target, dict)
    ]
    historic_gate = _historic_route_benchmark_gate(historic_route_benchmark_path)
    policy_gate = _route_policy_lifecycle_gate(route_policy)
    global_blockers = list(historic_gate.get("blockers") or [])
    global_blockers.extend(policy_gate.get("blockers") or [])
    global_warnings = list(policy_gate.get("warnings") or [])
    ready_targets = [row["owner_tui"] for row in targets if row["cutover_ready"]]
    promotion_ready_targets = [
        row["owner_tui"] for row in targets if row.get("promotion_ready")
    ]
    wave_one_targets = [row for row in targets if _coerce_int(row.get("wave")) == 1]
    wave_two_targets = [row for row in targets if _coerce_int(row.get("wave")) == 2]
    if global_blockers:
        readiness = "not_ready_for_cutover"
        ready_targets = []
    elif not ready_targets:
        readiness = "not_ready_for_cutover"
    elif len(ready_targets) == len(wave_one_targets):
        readiness = "ready_for_wave_1_limited_cutover"
    else:
        readiness = "partial_wave_1_cutover_ready"
    return {
        "schema": "norman.tui-cutover-readiness.v1",
        "generated_at": int(time.time()),
        "source_schema": flow_plan.get("schema"),
        "dry_run_only": True,
        "cutover_requires_operator_approval": True,
        "readiness": readiness,
        "global_blockers": global_blockers,
        "global_warnings": global_warnings,
        "historic_route_benchmark": historic_gate,
        "route_policy": policy_gate,
        "ready_targets": ready_targets,
        "promotion_ready_targets": promotion_ready_targets,
        "blocked_targets": [
            row["owner_tui"] for row in targets if not row["cutover_ready"]
        ],
        "promotion_blocked_targets": [
            row["owner_tui"] for row in targets if not row.get("promotion_ready")
        ],
        "thresholds": {
            "min_route_receipts": MIN_CUTOVER_ROUTE_RECEIPTS,
            "min_validator_pass_rate": MIN_CUTOVER_VALIDATOR_PASS_RATE,
            "max_manual_override_rate": MAX_CUTOVER_MANUAL_OVERRIDE_RATE,
            "max_fallback_rate": MAX_CUTOVER_FALLBACK_RATE,
            "min_cost_savings_vs_all_5_5": MIN_CUTOVER_COST_SAVINGS,
            "min_historic_route_benchmark_savings": MIN_HISTORIC_ROUTE_BENCHMARK_SAVINGS,
            "required_historic_route_policy_version": REQUIRED_HISTORIC_ROUTE_POLICY_VERSION,
            "required_historic_route_planner_action_policy_version": (
                REQUIRED_HISTORIC_ROUTE_PLANNER_ACTION_POLICY_VERSION
            ),
            "min_historic_route_planner_action_score": (
                MIN_HISTORIC_ROUTE_PLANNER_ACTION_SCORE
            ),
            "max_historic_route_benchmark_five_five_share": MAX_HISTORIC_ROUTE_BENCHMARK_FIVE_FIVE_SHARE,
            "required_boundary_violations": 0,
            "required_synthetic_receipts": 0,
            "required_live_write_attempts": 0,
            "required_operator_approval_routes": 0,
            "required_final_authority_routes": 0,
            "required_route_receipt_chain_issues": 0,
        },
        "summary": {
            "target_count": len(targets),
            "wave_1_target_count": len(wave_one_targets),
            "wave_2_target_count": len(wave_two_targets),
            "ready_target_count": len(ready_targets),
            "promotion_ready_target_count": len(promotion_ready_targets),
            "wave_2_ready_target_count": sum(
                1 for row in wave_two_targets if row.get("promotion_ready")
            ),
            "blocked_target_count": len(targets) - len(ready_targets),
            "receipt_count": sum(
                _coerce_int(row.get("metrics", {}).get("receipt_count"))
                for row in targets
            ),
            "boundary_violation_count": sum(
                _coerce_int(row.get("metrics", {}).get("boundary_violation_count"))
                for row in targets
            ),
            "synthetic_receipt_count": sum(
                _coerce_int(row.get("metrics", {}).get("synthetic_receipt_count"))
                for row in targets
            ),
            "live_write_attempt_count": sum(
                _coerce_int(row.get("metrics", {}).get("live_write_attempt_count"))
                for row in targets
            ),
            "route_drift_count": sum(
                _coerce_int(row.get("metrics", {}).get("route_drift_count"))
                for row in targets
            ),
            "route_receipt_chain_issue_count": sum(
                _coerce_int(row.get("metrics", {}).get("chain_issue_count"))
                for row in targets
            ),
            "strict_receipt_issue_count": sum(
                _coerce_int(row.get("metrics", {}).get("strict_issue_count"))
                for row in targets
            ),
            "historic_route_benchmark_gate": historic_gate.get("gate"),
            "historic_route_benchmark_savings": historic_gate.get(
                "savings_vs_all_bedrock_5_5_xhigh"
            ),
            "historic_route_benchmark_accuracy_fail_count": historic_gate.get(
                "accuracy_gate_fail_count"
            ),
            "historic_route_benchmark_policy_version": historic_gate.get(
                "policy_version"
            ),
            "historic_route_benchmark_policy_fail_count": historic_gate.get(
                "routing_policy_compliance_fail_count"
            ),
            "historic_route_planner_action_policy_version": historic_gate.get(
                "planner_action_policy_version"
            ),
            "historic_route_planner_action_case_count": historic_gate.get(
                "planner_action_case_count"
            ),
            "historic_route_planner_action_fail_count": historic_gate.get(
                "planner_action_fail_count"
            ),
            "historic_route_median_planner_action_score": historic_gate.get(
                "median_planner_action_score"
            ),
            "historic_route_benchmark_lower_model_case_count": historic_gate.get(
                "lower_model_case_count"
            ),
            "historic_route_benchmark_five_five_share": historic_gate.get(
                "median_five_five_token_share_vs_raw"
            ),
            "route_policy_gate": policy_gate.get("gate"),
            "route_policy_state": (policy_gate.get("lifecycle") or {}).get("state"),
            "route_policy_id": (policy_gate.get("lifecycle") or {}).get("policy_id"),
            "route_policy_hash": (policy_gate.get("lifecycle") or {}).get(
                "policy_hash"
            ),
        },
        "cutover_scope": {
            "allowed": [
                "route bounded worker/draft tasks through the selected hybrid lane",
                "keep 5.4 verifier and 5.5 final-authority gates active",
                "emit route receipts for every decision",
                "fall back to 5.5 final authority only on validator or operator signal",
            ],
            "blocked": [
                "autonomous live writes",
                "BBS ACK/DONE/BLOCKED",
                "service restart",
                "deploy",
                "DNS/Caddy/cloud/vendor mutation",
                "final authority on control-plane, netops, gold-book, or theseus",
            ],
        },
        "targets": targets,
    }


def render_cutover_readiness_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    historic = (
        report.get("historic_route_benchmark")
        if isinstance(report.get("historic_route_benchmark"), dict)
        else {}
    )
    route_policy = (
        report.get("route_policy")
        if isinstance(report.get("route_policy"), dict)
        else {}
    )
    route_policy_life = (
        route_policy.get("lifecycle")
        if isinstance(route_policy.get("lifecycle"), dict)
        else {}
    )
    historic_savings = _safe_float(historic.get("savings_vs_all_bedrock_5_5_xhigh"))
    historic_savings_label = (
        "-" if historic_savings is None else f"{historic_savings * 100:.1f}%"
    )
    historic_action_score = _safe_float(historic.get("median_planner_action_score"))
    historic_action_score_label = (
        "-" if historic_action_score is None else f"{historic_action_score * 100:.1f}%"
    )
    lines = [
        "# TUI Cutover Readiness",
        "",
        "Dry-run readiness report. This does not deploy, restart, ACK BBS handoffs, or mutate live state.",
        "",
        "## Summary",
        "",
        f"- Readiness: {report.get('readiness')}",
        f"- Cutover requires approval: {report.get('cutover_requires_operator_approval')}",
        f"- Ready targets: {', '.join(report.get('ready_targets') or []) or '-'}",
        f"- Promotion-ready targets: {', '.join(report.get('promotion_ready_targets') or []) or '-'}",
        f"- Blocked targets: {', '.join(report.get('blocked_targets') or []) or '-'}",
        f"- Targets: {summary.get('target_count')}",
        f"- Wave 1 targets: {summary.get('wave_1_target_count')}",
        f"- Wave 2 targets: {summary.get('wave_2_target_count')}",
        f"- Wave 2 promotion-ready: {summary.get('wave_2_ready_target_count')}",
        f"- Route receipts: {summary.get('receipt_count')}",
        f"- Boundary violations: {summary.get('boundary_violation_count')}",
        f"- Synthetic receipts: {summary.get('synthetic_receipt_count')}",
        f"- Live write attempts: {summary.get('live_write_attempt_count')}",
        f"- Route drifted receipts: {summary.get('route_drift_count')}",
        f"- Route receipt chain issues: {summary.get('route_receipt_chain_issue_count')}",
        f"- Historic route benchmark: {historic.get('gate', 'not_configured')}",
        f"- Historic route benchmark savings: {historic_savings_label}",
        f"- Historic planner action cases/failures: {historic.get('planner_action_case_count', '-')}/{historic.get('planner_action_fail_count', '-')}",
        f"- Historic planner action score: {historic_action_score_label}",
        f"- Route policy gate: {route_policy.get('gate', '-')}",
        f"- Route policy lifecycle: {route_policy_life.get('state', '-')}",
        f"- Route policy ID: {route_policy_life.get('policy_id', '-')}",
        "",
    ]
    if report.get("global_warnings"):
        lines.extend(["## Global Warnings", ""])
        lines.extend(f"- {item}" for item in report.get("global_warnings") or [])
        lines.append("")
    if report.get("global_blockers"):
        lines.extend(["## Global Blockers", ""])
        lines.extend(f"- {item}" for item in report.get("global_blockers") or [])
        lines.append("")
        lines.extend(
            [
                "## Targets",
                "",
                "| Owner TUI | Wave | Promotion | Cutover | Receipts | Validator | Manual override | Fallback | Savings | Blockers | Next action |",
                "|---|---:|---|---|---:|---:|---:|---:|---:|---|---|",
            ]
        )
    for row in report.get("targets", []):
        metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), dict) else {}
        savings = metrics.get("cost_savings_vs_all_5_5")
        lines.append(
            "| {owner} | {wave} | {promotion} | {cutover} | {receipts} | {validator:.1%} | {override:.1%} | {fallback:.1%} | {savings} | {blockers} | {next_actions} |".format(
                owner=_cell(row.get("owner_tui")),
                wave=_coerce_int(row.get("wave")),
                promotion=_cell(row.get("promotion_gate")),
                cutover=_cell(row.get("cutover_gate")),
                receipts=_coerce_int(metrics.get("receipt_count")),
                validator=float(metrics.get("validator_pass_rate") or 0.0),
                override=float(metrics.get("manual_override_rate") or 0.0),
                fallback=float(metrics.get("fallback_rate") or 0.0),
                savings=("-" if savings is None else f"{float(savings) * 100:.1f}%"),
                blockers=_cell("; ".join(row.get("blockers") or [])),
                next_actions=_cell("; ".join(row.get("next_actions") or [])),
            )
        )
    lines.extend(["", "## Allowed Cutover Scope", ""])
    scope = (
        report.get("cutover_scope")
        if isinstance(report.get("cutover_scope"), dict)
        else {}
    )
    lines.extend(f"- {item}" for item in scope.get("allowed", []))
    lines.extend(["", "## Blocked Cutover Scope", ""])
    lines.extend(f"- {item}" for item in scope.get("blocked", []))
    return "\n".join(lines) + "\n"


def build_route_receipt_template(target_row: dict[str, Any]) -> dict[str, Any]:
    owner = str(target_row.get("owner_tui") or "unknown")
    return {
        "receipt_id": f"{owner}-shadow-000001",
        "receipt_source": "template_not_live_observation",
        "previous_receipt_hash": "replace-with-previous-live-receipt-hash-or-empty",
        "receipt_hash": "replace-with-computed-live-receipt-hash",
        "synthetic": True,
        "created_at": int(time.time()),
        "owner_tui": owner,
        "prompt_id": "replace-with-live-shadow-prompt-id",
        "benchmark_skill_id": "replace-with-benchmark-skill-id",
        "requested_action": "replace-with-observed-requested-action",
        "selected_model_tier": "replace-with-small-medium-5_4-or-5_5",
        "selected_model": "replace-with-selected-model",
        "routing_score": 0.0,
        "routing_bands": {
            "worker": "replace-with-worker-band",
            "verifier": "replace-with-verifier-band",
            "final": "replace-with-final-band",
        },
        "allowed_role": "replace-with-worker_draft-verifier-or-final",
        "validator_gate": "replace-with-pass-fail-or-held",
        "escalation_trigger": "",
        "fallback_used": "",
        "estimated_cost_usd": 0.0,
        "baseline_all_5_5_cost_usd": 0.0,
        "validator_passed": False,
        "manual_override": False,
        "boundary_violation": False,
        "latency_ms": 0,
        "operator_approval_required": False,
        "final_authority_required": False,
        "live_write_attempted": False,
        "outcome": "template_not_observed",
        "evidence_refs": [
            "replace-with-status-snapshot",
            "replace-with-validator-or-runbook-ref",
        ],
    }


def build_route_receipt_manifest(
    flow_plan: dict[str, Any],
    *,
    receipt_dir: Path = DEFAULT_ROUTE_RECEIPT_DIR,
    template_dir: Path = DEFAULT_ROUTE_RECEIPT_TEMPLATE_DIR,
) -> dict[str, Any]:
    if flow_plan.get("schema") != "norman.tui-flow-canary-plan.v1":
        raise ValueError("flow plan is not a TUI flow canary plan")
    receipt_contract = (
        flow_plan.get("route_receipt_contract")
        if isinstance(flow_plan.get("route_receipt_contract"), dict)
        else {}
    )
    rows = []
    for target in flow_plan.get("targets", []):
        if not isinstance(target, dict):
            continue
        owner = str(target.get("owner_tui") or "")
        wave = _coerce_int(target.get("wave"))
        rows.append(
            {
                "owner_tui": owner,
                "wave": wave,
                "launch_gate": target.get("launch_gate"),
                "flow_mode": target.get("flow_mode"),
                "cutover_candidate": wave == 1,
                "capture_required": wave in {1, 2},
                "receipt_path": str(_route_receipt_path(target, receipt_dir)),
                "template_path": str(template_dir / f"{owner}.template.json"),
                "append_mode": "jsonl_one_receipt_per_shadow_route_decision",
                "required_receipts_before_cutover": MIN_CUTOVER_ROUTE_RECEIPTS
                if wave == 1
                else 0,
                "blocked_actions": list(target.get("blocked_actions") or []),
                "template_synthetic": True,
            }
        )
    wave_one_count = sum(1 for row in rows if row["wave"] == 1)
    return {
        "schema": "norman.tui-route-receipt-manifest.v1",
        "generated_at": int(time.time()),
        "source_schema": flow_plan.get("schema"),
        "dry_run_only": True,
        "templates_are_synthetic": True,
        "templates_count_toward_cutover": False,
        "receipt_contract": receipt_contract,
        "summary": {
            "target_count": len(rows),
            "wave_1_target_count": wave_one_count,
            "capture_required_target_count": sum(
                1 for row in rows if row["capture_required"]
            ),
            "required_wave_1_receipts_total": (
                wave_one_count * MIN_CUTOVER_ROUTE_RECEIPTS
            ),
        },
        "collection_rules": [
            "append one JSON object per shadow route decision",
            "set synthetic=false only for observed live shadow routing decisions",
            "do not copy templates into receipt sinks as evidence",
            "include baseline_all_5_5_cost_usd for savings measurement",
            "set live_write_attempted=true if anything attempted a live mutation",
            "set operator_approval_required=true for deploy/restart/BBS close-loop/DNS/Caddy/cloud/vendor routes",
            "set final_authority_required=true when the route needs 5.5 final authority or human approval",
        ],
        "targets": rows,
    }


def render_route_receipt_manifest_markdown(manifest: dict[str, Any]) -> str:
    summary = (
        manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {}
    )
    contract = (
        manifest.get("receipt_contract")
        if isinstance(manifest.get("receipt_contract"), dict)
        else {}
    )
    lines = [
        "# TUI Route Receipt Manifest",
        "",
        "Dry-run capture manifest. Templates are synthetic and do not count toward cutover readiness.",
        "",
        "## Summary",
        "",
        f"- Targets: {summary.get('target_count')}",
        f"- Wave 1 targets: {summary.get('wave_1_target_count')}",
        f"- Capture-required targets: {summary.get('capture_required_target_count')}",
        f"- Required wave 1 receipts total: {summary.get('required_wave_1_receipts_total')}",
        f"- Templates count toward cutover: {manifest.get('templates_count_toward_cutover')}",
        "",
        "## Contract",
        "",
        f"- Schema: {contract.get('schema')}",
        "- Required fields: " + ", ".join(contract.get("required_fields") or []),
        "",
        "## Targets",
        "",
        "| Owner TUI | Wave | Capture | Cutover candidate | Receipt sink | Template |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in manifest.get("targets", []):
        lines.append(
            "| {owner} | {wave} | {capture} | {candidate} | {sink} | {template} |".format(
                owner=_cell(row.get("owner_tui")),
                wave=_coerce_int(row.get("wave")),
                capture=row.get("capture_required"),
                candidate=row.get("cutover_candidate"),
                sink=_cell(row.get("receipt_path")),
                template=_cell(row.get("template_path")),
            )
        )
    lines.extend(["", "## Collection Rules", ""])
    lines.extend(f"- {item}" for item in manifest.get("collection_rules", []))
    return "\n".join(lines) + "\n"


def _select_route_receipt_launch_target(
    manifest: dict[str, Any], owner_tui: str = ""
) -> dict[str, Any]:
    targets = [row for row in manifest.get("targets", []) if isinstance(row, dict)]
    if owner_tui:
        for row in targets:
            if str(row.get("owner_tui") or "") == owner_tui:
                return row
        raise ValueError(f"route receipt manifest has no target for {owner_tui}")
    for row in targets:
        if (
            _safe_bool(row.get("cutover_candidate"))
            and _coerce_int(row.get("wave")) == 1
        ):
            return row
    for row in targets:
        if _safe_bool(row.get("capture_required")):
            return row
    raise ValueError("route receipt manifest has no capture target")


def _receipt_sink_status(path: Path, *, prepare: bool = False) -> dict[str, Any]:
    prepared = False
    errors: list[str] = []
    try:
        if prepare:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
            prepared = True
    except OSError as exc:
        errors.append(str(exc))
    exists = path.exists()
    parent_exists = path.parent.exists()
    return {
        "path": str(path),
        "exists": exists,
        "parent_exists": parent_exists,
        "prepared": prepared,
        "writable": bool(parent_exists and os.access(path.parent, os.W_OK)),
        "errors": errors,
    }


def build_route_receipt_launch_plan(
    manifest: dict[str, Any],
    *,
    owner_tui: str = "",
    prepare_sink: bool = False,
) -> dict[str, Any]:
    if manifest.get("schema") != "norman.tui-route-receipt-manifest.v1":
        raise ValueError("route receipt manifest is not valid")
    target = _select_route_receipt_launch_target(manifest, owner_tui)
    owner = str(target.get("owner_tui") or "")
    receipt_path = Path(str(target.get("receipt_path") or ""))
    sink = _receipt_sink_status(receipt_path, prepare=prepare_sink)
    wave = _coerce_int(target.get("wave"))
    launch_gate = str(target.get("launch_gate") or "")
    ready = (
        _safe_bool(target.get("capture_required"))
        and wave == 1
        and launch_gate == "ready_for_shadow_route_receipts"
        and bool(sink["exists"])
        and bool(sink["writable"])
        and not sink["errors"]
    )
    blocked_reasons: list[str] = []
    if not _safe_bool(target.get("capture_required")):
        blocked_reasons.append("target does not require route receipt capture")
    if wave != 1:
        blocked_reasons.append("target is not a wave-1 launch target")
    if launch_gate != "ready_for_shadow_route_receipts":
        blocked_reasons.append(f"launch gate is {launch_gate or 'missing'}")
    if not sink["exists"]:
        blocked_reasons.append("route receipt sink does not exist")
    if not sink["writable"]:
        blocked_reasons.append("route receipt sink directory is not writable")
    blocked_reasons.extend(str(error) for error in sink["errors"])
    return {
        "schema": "norman.tui-route-receipt-launch-plan.v1",
        "generated_at": int(time.time()),
        "source_schema": manifest.get("schema"),
        "dry_run_only": True,
        "live_mutation_performed": False,
        "owner_tui": owner,
        "wave": wave,
        "launch_gate": launch_gate,
        "launch_status": (
            "ready_for_operator_approved_shadow_capture"
            if ready
            else "blocked_before_shadow_capture"
        ),
        "blocked_reasons": blocked_reasons,
        "receipt_path": str(receipt_path),
        "receipt_sink": sink,
        "required_receipts_before_cutover": target.get(
            "required_receipts_before_cutover"
        ),
        "env": {
            "NORMAN_CODEX_ROUTE_RECEIPTS_ENABLED": "1",
            "NORMAN_CODEX_ROUTE_RECEIPT_OWNER_TUI": owner,
            "NORMAN_CODEX_ROUTE_RECEIPT_PATH": str(receipt_path),
            "NORMAN_CODEX_ROUTE_RECEIPT_ITEMS": "250",
        },
        "activation_requires_operator_approval": True,
        "activation_steps": [
            "verify target TUI is idle and reachable",
            "apply the env vars to the target TUI web service",
            "perform an operator-approved web-only restart for that TUI",
            "run shadow-only prompts until the receipt sink has 50 real records",
            "run cutover readiness before any live default change",
        ],
        "allowed_actions": [
            "shadow route decision",
            "bounded read/status/evidence retrieval",
            "draft-only answer",
            "append route receipt",
        ],
        "blocked_actions": list(target.get("blocked_actions") or []),
        "success_metrics": [
            "50 nonsynthetic route receipts",
            "validator pass rate >= 98%",
            "boundary violations == 0",
            "live write attempts == 0",
            "manual override rate <= 5%",
            "baseline_all_5_5_cost_usd present on every receipt",
        ],
    }


def render_route_receipt_launch_plan_markdown(plan: dict[str, Any]) -> str:
    lines = [
        "# TUI Route Receipt Launch Plan",
        "",
        "Dry-run launch packet. This does not deploy, restart, enqueue work, call models, ACK BBS handoffs, or mutate live state.",
        "",
        "## Status",
        "",
        f"- Owner TUI: {plan.get('owner_tui')}",
        f"- Launch status: {plan.get('launch_status')}",
        f"- Live mutation performed: {plan.get('live_mutation_performed')}",
        f"- Receipt path: {plan.get('receipt_path')}",
        f"- Required receipts before cutover: {plan.get('required_receipts_before_cutover')}",
        "",
        "## Environment",
        "",
    ]
    env = plan.get("env") if isinstance(plan.get("env"), dict) else {}
    lines.extend(f"- `{key}={value}`" for key, value in env.items())
    lines.extend(["", "## Blockers", ""])
    blockers = plan.get("blocked_reasons") or []
    lines.extend(f"- {item}" for item in blockers)
    if not blockers:
        lines.append("- none")
    lines.extend(["", "## Activation Steps", ""])
    lines.extend(f"- {item}" for item in plan.get("activation_steps", []))
    lines.extend(["", "## Hard Stops", ""])
    lines.extend(f"- {item}" for item in plan.get("blocked_actions", []))
    lines.extend(["", "## Success Metrics", ""])
    lines.extend(f"- {item}" for item in plan.get("success_metrics", []))
    return "\n".join(lines) + "\n"


def build_journal(reports: list[dict[str, Any]]) -> dict[str, Any]:
    final_report = reports[-1] if reports else {}
    rows_by_cycle = [
        {
            "cycle": report.get("cycle"),
            "generated_at": report.get("generated_at"),
            "summary": report.get("summary", {}),
            "rows": [
                {
                    "slug": row.get("target", {}).get("slug"),
                    "loop_ready": row.get("loop_ready"),
                    "state": row.get("status", {}).get("state"),
                    "pending": row.get("status", {}).get("pending"),
                    "queue_depth": row.get("status", {}).get("queue_depth"),
                    "bbs_missing_context": row.get("status", {}).get(
                        "bbs_missing_context"
                    ),
                    "bbs_waiting_pickup": row.get("status", {}).get(
                        "bbs_waiting_pickup"
                    ),
                    "optimizer_confidence_score": row.get("optimizer_confidence_score"),
                    "optimizer_confidence_band": row.get("optimizer_confidence_band"),
                    "route": (
                        f"{row.get('status', {}).get('selected_runtime')}/"
                        f"{row.get('status', {}).get('selected_model')}"
                    ),
                    "moves": [move.get("move_id") for move in row.get("moves", [])],
                }
                for row in report.get("rows", [])
            ],
        }
        for report in reports
    ]
    all_rows = [row for report in reports for row in report.get("rows", [])]
    approval_required_moves = sum(
        1
        for report in reports
        for row in report.get("rows", [])
        for move in row.get("moves", [])
        if move.get("approval_required")
    )
    return {
        "schema": "norman.work-loop-canary-journal.v1",
        "generated_at": int(time.time()),
        "cycles": len(reports),
        "summary": {
            "all_cycles_loop_ready": all(row.get("loop_ready") for row in all_rows)
            if all_rows
            else False,
            "approval_required_moves": approval_required_moves,
            "continuous_loop_enabled": False,
            "final_summary": final_report.get("summary", {}),
        },
        "cycles_detail": rows_by_cycle,
    }


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    cost_basis = (
        report.get("cost_basis") if isinstance(report.get("cost_basis"), dict) else {}
    )
    selected_mode = (
        cost_basis.get("selected_mode")
        if isinstance(cost_basis.get("selected_mode"), dict)
        else {}
    )
    sample_cost = (
        cost_basis.get("sample_ticket_cleanup")
        if isinstance(cost_basis.get("sample_ticket_cleanup"), dict)
        else {}
    )
    always_on_plan = (
        report.get("always_on_plan")
        if isinstance(report.get("always_on_plan"), dict)
        else {}
    )
    lines = [
        "# Work Loop Canary",
        "",
        "Dry-run only. This report checks whether selected TUIs are ready for a continuous obvious-move loop. It does not enqueue work, call models, ACK BBS handoffs, restart services, deploy, write to live Sheets, or inspect HAL.",
        "",
        "## Summary",
        "",
        f"- Architecture mode: {report.get('architecture_mode')}",
        f"- Mode label: {selected_mode.get('label', '')}",
        f"- Targets: {summary.get('targets')}",
        f"- Reachable: {summary.get('reachable')}",
        f"- Route OK: {summary.get('route_ok')}",
        f"- Idle/loop-ready: {summary.get('idle_ready')}",
        f"- Optimizer green targets: {summary.get('optimizer_ready')}",
        f"- Confidence min/avg: {summary.get('confidence_min')} / {summary.get('confidence_avg')}",
        f"- Shadow rollout recommendation: {summary.get('shadow_rollout_recommendation')}",
        f"- Always-on shadow gate: {summary.get('always_on_shadow_gate')}",
        f"- Live enable requires approval: {summary.get('always_on_live_enable_requires_approval')}",
        f"- BBS missing-context targets: {summary.get('bbs_missing_context_targets')}",
        f"- BBS waiting-pickup targets: {summary.get('bbs_waiting_pickup_targets')}",
        f"- Automatic safe moves identified: {summary.get('automatic_moves')}",
        f"- Approval-required moves identified: {summary.get('approval_required_moves')}",
        f"- HAL background discovery allowed: {summary.get('hal_background_discovery_allowed')}",
        f"- Continuous loop enabled: {summary.get('continuous_loop_enabled')}",
        "",
        "## Cost Basis",
        "",
        f"- Label: {cost_basis.get('estimate_label', '')}",
        f"- Status-loop model calls: {cost_basis.get('status_loop_model_calls')}",
        f"- Status-loop estimated USD: {cost_basis.get('status_loop_estimated_usd')}",
        f"- Sample input/output tokens: {sample_cost.get('input_tokens'):,} / {sample_cost.get('output_tokens'):,}",
        f"- Full direct GPT-5.5 Flex sample: ${sample_cost.get('full_direct_5_5_flex_usd')}",
        f"- Hybrid direct estimated sample: ${sample_cost.get('hybrid_direct_estimated_usd')} ({sample_cost.get('hybrid_ratio_vs_direct_5_5_flex')}x direct GPT-5.5 Flex)",
        f"- Selected mode direct estimated sample: ${sample_cost.get('selected_mode_direct_estimated_usd')} ({sample_cost.get('selected_ratio_vs_direct_5_5_flex')}x direct GPT-5.5 Flex)",
        f"- Full Bedrock GPT-5.5 us-east-2 sample: ${sample_cost.get('full_bedrock_5_5_us_east_2_usd')}",
        "",
        "## Always-On Loop Plan",
        "",
        f"- Fast-loop interval: {always_on_plan.get('fast_loop_interval_seconds')}s ({always_on_plan.get('fast_loop_cycles_per_day')} cycles/day)",
        f"- Unchanged steady-state model spend: ${always_on_plan.get('unchanged_daily_usd')}/day",
        f"- Max changed tickets per model cycle: {always_on_plan.get('max_changed_tickets_per_cycle')}",
        f"- Daily budget: ${always_on_plan.get('daily_budget_usd')}",
        f"- Expected changed-ticket cost: ${always_on_plan.get('expected_usd_per_changed_ticket')} each",
        f"- P95 changed-ticket cost: ${always_on_plan.get('p95_usd_per_changed_ticket')} each",
        f"- Expected changed-cycle cost: ${always_on_plan.get('expected_usd_per_changed_cycle')}",
        f"- P95 changed-cycle cost: ${always_on_plan.get('p95_usd_per_changed_cycle')}",
        f"- Expected changed cycles affordable/day: {always_on_plan.get('expected_changed_cycles_affordable_per_day')}",
        f"- P95 changed cycles affordable/day: {always_on_plan.get('p95_changed_cycles_affordable_per_day')}",
        f"- Spend gate: {always_on_plan.get('spend_gate')} ({'; '.join(str(item) for item in always_on_plan.get('spend_gate_reasons', []))})",
        f"- Live enable approval required: {always_on_plan.get('operator_approval_required_for_live_enable')}",
        "",
        "## Architecture",
        "",
        "| Tier | Lane | Cadence | Model | Purpose |",
        "|---|---|---|---|---|",
    ]
    for item in report.get("architecture", []):
        lines.append(
            "| {tier} | {name} | {cadence} | {model} | {purpose} |".format(
                tier=_cell(item.get("tier", "")),
                name=_cell(item.get("name", "")),
                cadence=_cell(item.get("cadence", "")),
                model=_cell(item.get("model", "")),
                purpose=_cell(item.get("purpose", "")),
            )
        )

    lines.extend(
        [
            "",
            "## Targets",
            "",
            "| Target | Reach | State | Queue | Route | BBS | Confidence | Loop-ready | Boundary |",
            "|---|---:|---|---:|---|---|---:|---:|---|",
        ]
    )
    for row in report.get("rows", []):
        target = row.get("target", {})
        status = row.get("status", {})
        route = f"{status.get('selected_runtime')}/{status.get('selected_model')}"
        bbs = (
            f"missing={_coerce_int(status.get('bbs_missing_context'))}; "
            f"waiting={_coerce_int(status.get('bbs_waiting_pickup'))}; "
            f"picked={_coerce_int(status.get('bbs_picked_up'))}"
        )
        lines.append(
            "| {target} | {reach} | {state} | {queue} | {route} | {bbs} | {confidence} | {ready} | {boundary} |".format(
                target=_cell(target.get("label") or target.get("slug")),
                reach="yes" if status.get("reachable") else "no",
                state=_cell(status.get("state") or status.get("error") or ""),
                queue=_coerce_int(status.get("queue_depth")),
                route=_cell(route),
                bbs=_cell(bbs),
                confidence=(
                    f"{row.get('optimizer_confidence_score')}"
                    f"/{row.get('optimizer_confidence_band')}"
                ),
                ready="yes" if row.get("loop_ready") else "no",
                boundary=_cell(target.get("approval_boundary", "")),
            )
        )

    lines.extend(["", "## Moves", ""])
    for row in report.get("rows", []):
        target = row.get("target", {})
        lines.extend(
            [
                f"### {_cell(target.get('label') or target.get('slug'))}",
                "",
                "| Move | Priority | Lane | Auto | Approval | Model lane | Next action |",
                "|---|---|---|---:|---:|---|---|",
            ]
        )
        for move in row.get("moves", []):
            lines.append(
                "| {move_id} | {priority} | {lane} | {auto} | {approval} | {model} | {next_action} |".format(
                    move_id=_cell(move.get("move_id", "")),
                    priority=_cell(move.get("priority", "")),
                    lane=_cell(move.get("lane", "")),
                    auto="yes" if move.get("automatic") else "no",
                    approval="yes" if move.get("approval_required") else "no",
                    model=_cell(move.get("model_lane", "")),
                    next_action=_cell(move.get("next_action", "")),
                )
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a dry-run canary for CP/Gold Book continuous obvious-move loops."
    )
    parser.add_argument(
        "--source-json",
        type=Path,
        help="Use saved status JSON instead of fetching live endpoints.",
    )
    parser.add_argument(
        "--targets",
        default="control-plane,gold-book",
        help="Comma-separated target slugs to include.",
    )
    parser.add_argument(
        "--mode",
        choices=sorted(ARCHITECTURE_MODES),
        default=DEFAULT_MODE,
        help="Architecture/cost mode to record in the canary report.",
    )
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument(
        "--loop-count",
        type=int,
        default=1,
        help="Run a supervised dry loop for N cycles. No background service is started.",
    )
    parser.add_argument(
        "--loop-interval",
        type=float,
        default=0.0,
        help="Seconds to sleep between supervised dry-loop cycles.",
    )
    parser.add_argument(
        "--fast-loop-interval-seconds",
        type=int,
        default=DEFAULT_FAST_LOOP_INTERVAL_SECONDS,
        help="Planned always-on status polling cadence for cost/readiness math.",
    )
    parser.add_argument(
        "--max-changed-tickets-per-cycle",
        type=int,
        default=DEFAULT_MAX_CHANGED_TICKETS_PER_CYCLE,
        help="Maximum changed tickets the model lane may process per spend cycle.",
    )
    parser.add_argument(
        "--daily-budget-usd",
        type=float,
        default=DEFAULT_DAILY_BUDGET_USD,
        help="Daily model-spend budget used for the always-on planning gate.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument(
        "--skill-matrix-json",
        type=Path,
        default=DEFAULT_SKILL_MATRIX_JSON,
        help="Work-domain skill matrix JSON used to build the TUI flow canary plan.",
    )
    parser.add_argument(
        "--flow-plan-targets",
        default="",
        help=(
            "Optional comma-separated owner_tui list for the flow plan. Default "
            "uses the benchmark rollout priority."
        ),
    )
    parser.add_argument(
        "--write-flow-plan",
        action="store_true",
        help="Also write the guarded TUI flow canary plan artifacts.",
    )
    parser.add_argument(
        "--flow-plan-only",
        action="store_true",
        help="Only write the guarded TUI flow canary plan; do not fetch TUI status.",
    )
    parser.add_argument(
        "--output-flow-plan-json",
        type=Path,
        default=DEFAULT_FLOW_PLAN_JSON,
    )
    parser.add_argument(
        "--output-flow-plan-md",
        type=Path,
        default=DEFAULT_FLOW_PLAN_MD,
    )
    parser.add_argument(
        "--flow-plan-json",
        type=Path,
        default=DEFAULT_FLOW_PLAN_JSON,
        help="Existing TUI flow canary plan JSON used for cutover readiness.",
    )
    parser.add_argument(
        "--route-receipt-dir",
        type=Path,
        default=DEFAULT_ROUTE_RECEIPT_DIR,
        help="Directory containing per-owner route receipt JSONL files.",
    )
    parser.add_argument(
        "--route-receipt-template-dir",
        type=Path,
        default=DEFAULT_ROUTE_RECEIPT_TEMPLATE_DIR,
        help="Directory for per-owner synthetic route receipt templates.",
    )
    parser.add_argument(
        "--write-route-receipt-manifest",
        action="store_true",
        help="Also write route receipt manifest and synthetic templates.",
    )
    parser.add_argument(
        "--route-receipt-manifest-only",
        action="store_true",
        help="Only write route receipt manifest/templates; do not fetch TUI status.",
    )
    parser.add_argument(
        "--output-route-receipt-manifest-json",
        type=Path,
        default=DEFAULT_ROUTE_RECEIPT_MANIFEST_JSON,
    )
    parser.add_argument(
        "--output-route-receipt-manifest-md",
        type=Path,
        default=DEFAULT_ROUTE_RECEIPT_MANIFEST_MD,
    )
    parser.add_argument(
        "--route-receipt-launch-plan-only",
        action="store_true",
        help=(
            "Only write the guarded route receipt launch packet; do not fetch TUI "
            "status or mutate live services."
        ),
    )
    parser.add_argument(
        "--launch-owner",
        default="",
        help=(
            "Owner TUI for the route receipt launch packet. Default uses the first "
            "wave-1 target from the manifest."
        ),
    )
    parser.add_argument(
        "--prepare-route-receipt-sink",
        action="store_true",
        help="Create the local JSONL receipt sink file if missing.",
    )
    parser.add_argument(
        "--output-route-receipt-launch-json",
        type=Path,
        default=DEFAULT_ROUTE_RECEIPT_LAUNCH_JSON,
    )
    parser.add_argument(
        "--output-route-receipt-launch-md",
        type=Path,
        default=DEFAULT_ROUTE_RECEIPT_LAUNCH_MD,
    )
    parser.add_argument(
        "--harvest-route-receipts",
        action="store_true",
        help=(
            "Read configured remote receipt sinks into the local route receipt "
            "directory before writing cutover readiness."
        ),
    )
    parser.add_argument(
        "--harvest-route-receipts-only",
        action="store_true",
        help=(
            "Only harvest configured remote route receipts; do not fetch TUI status "
            "or write cutover readiness."
        ),
    )
    parser.add_argument(
        "--harvest-route-receipt-owners",
        default="",
        help=(
            "Optional comma-separated owner_tui list to harvest. Default harvests "
            "all configured targets in the flow plan."
        ),
    )
    parser.add_argument(
        "--output-route-receipt-harvest-json",
        type=Path,
        default=DEFAULT_ROUTE_RECEIPT_HARVEST_JSON,
    )
    parser.add_argument(
        "--output-route-receipt-harvest-md",
        type=Path,
        default=DEFAULT_ROUTE_RECEIPT_HARVEST_MD,
    )
    parser.add_argument(
        "--write-cutover-readiness",
        action="store_true",
        help="Also write the dry-run cutover readiness artifacts.",
    )
    parser.add_argument(
        "--cutover-readiness-only",
        action="store_true",
        help="Only write cutover readiness artifacts; do not fetch TUI status.",
    )
    parser.add_argument(
        "--output-cutover-readiness-json",
        type=Path,
        default=DEFAULT_CUTOVER_READINESS_JSON,
    )
    parser.add_argument(
        "--output-cutover-readiness-md",
        type=Path,
        default=DEFAULT_CUTOVER_READINESS_MD,
    )
    parser.add_argument(
        "--historic-route-benchmark-json",
        type=Path,
        default=None,
        help=(
            "Optional historic shadow planner route benchmark JSON. When supplied, "
            "cutover readiness holds unless its cost/accuracy gate passes."
        ),
    )
    parser.add_argument(
        "--output-journal-json",
        type=Path,
        help="Write a per-cycle journal when running with --loop-count > 1.",
    )
    parser.add_argument(
        "--ticket-id",
        help=(
            "Optional internal ticket id. When set, append a ticket token/cost "
            "ledger record for this canary run."
        ),
    )
    parser.add_argument("--ticket-actor", default="norman")
    parser.add_argument(
        "--ticket-cost-ledger-jsonl",
        type=Path,
        default=DEFAULT_TICKET_COST_LEDGER_JSONL,
    )
    parser.add_argument(
        "--ticket-runtime",
        default="local",
        help="Runtime to record for ticket cost logging. Default is local dry-run.",
    )
    parser.add_argument(
        "--ticket-model",
        default="none",
        help="Model to record for ticket cost logging. Default is none.",
    )
    parser.add_argument("--ticket-service-tier", default="")
    parser.add_argument(
        "--ticket-price-basis",
        default="none",
        choices=[
            "auto",
            "none",
            "openai-direct-standard",
            "openai-direct-flex",
            "bedrock-us-east-2",
        ],
    )
    parser.add_argument("--ticket-input-tokens", type=int, default=0)
    parser.add_argument("--ticket-cached-input-tokens", type=int, default=0)
    parser.add_argument("--ticket-output-tokens", type=int, default=0)
    parser.add_argument("--ticket-reasoning-output-tokens", type=int, default=0)
    parser.add_argument("--ticket-total-tokens", type=int, default=0)
    parser.add_argument("--ticket-notes", default="")
    parser.add_argument("--print-md", action="store_true")
    return parser.parse_args()


def _select_targets(targets: str) -> dict[str, LoopTarget]:
    selected: dict[str, LoopTarget] = {}
    for raw in targets.split(","):
        slug = raw.strip()
        if not slug:
            continue
        if slug not in LOOP_TARGETS:
            raise ValueError(f"unknown target: {slug}")
        selected[slug] = LOOP_TARGETS[slug]
    return selected


def _parse_flow_plan_targets(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _parse_owner_filter(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _write_flow_plan_artifacts(args: argparse.Namespace) -> dict[str, Any]:
    skill_matrix = load_skill_matrix_source(args.skill_matrix_json)
    plan = build_flow_canary_plan(
        skill_matrix,
        requested_owners=_parse_flow_plan_targets(args.flow_plan_targets),
    )
    markdown = render_flow_canary_plan_markdown(plan)
    args.output_flow_plan_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_flow_plan_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_flow_plan_json.write_text(
        json.dumps(plan, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    args.output_flow_plan_md.write_text(markdown, encoding="utf-8")
    return plan


def _write_route_receipt_harvest_artifacts(
    args: argparse.Namespace, flow_plan: dict[str, Any] | None = None
) -> dict[str, Any]:
    plan = (
        flow_plan
        if flow_plan is not None
        else load_flow_plan_source(args.flow_plan_json)
    )
    report = harvest_route_receipts(
        plan,
        receipt_dir=args.route_receipt_dir,
        owners=_parse_owner_filter(args.harvest_route_receipt_owners),
    )
    markdown = render_route_receipt_harvest_markdown(report)
    args.output_route_receipt_harvest_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_route_receipt_harvest_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_route_receipt_harvest_json.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    args.output_route_receipt_harvest_md.write_text(markdown, encoding="utf-8")
    return report


def _write_cutover_readiness_artifacts(args: argparse.Namespace) -> dict[str, Any]:
    flow_plan = load_flow_plan_source(args.flow_plan_json)
    if args.harvest_route_receipts:
        _write_route_receipt_harvest_artifacts(args, flow_plan=flow_plan)
    report = build_cutover_readiness_report(
        flow_plan,
        receipt_dir=args.route_receipt_dir,
        historic_route_benchmark_path=args.historic_route_benchmark_json,
    )
    markdown = render_cutover_readiness_markdown(report)
    args.output_cutover_readiness_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_cutover_readiness_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_cutover_readiness_json.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    args.output_cutover_readiness_md.write_text(markdown, encoding="utf-8")
    return report


def _write_route_receipt_manifest_artifacts(args: argparse.Namespace) -> dict[str, Any]:
    flow_plan = load_flow_plan_source(args.flow_plan_json)
    manifest = build_route_receipt_manifest(
        flow_plan,
        receipt_dir=args.route_receipt_dir,
        template_dir=args.route_receipt_template_dir,
    )
    markdown = render_route_receipt_manifest_markdown(manifest)
    args.output_route_receipt_manifest_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_route_receipt_manifest_md.parent.mkdir(parents=True, exist_ok=True)
    args.route_receipt_template_dir.mkdir(parents=True, exist_ok=True)
    targets_by_owner = {
        str(target.get("owner_tui") or ""): target
        for target in flow_plan.get("targets", [])
        if isinstance(target, dict)
    }
    expected_template_paths: set[Path] = set()
    for row in manifest.get("targets", []):
        owner = str(row.get("owner_tui") or "")
        template_path = Path(str(row.get("template_path")))
        expected_template_paths.add(template_path.resolve())
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text(
            json.dumps(
                build_route_receipt_template(targets_by_owner.get(owner, row)),
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    for stale_template in args.route_receipt_template_dir.glob("*.template.json"):
        if stale_template.resolve() not in expected_template_paths:
            stale_template.unlink()
    args.output_route_receipt_manifest_json.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    args.output_route_receipt_manifest_md.write_text(markdown, encoding="utf-8")
    return manifest


def _write_route_receipt_launch_artifacts(args: argparse.Namespace) -> dict[str, Any]:
    manifest = json.loads(
        args.output_route_receipt_manifest_json.read_text(encoding="utf-8")
    )
    if not isinstance(manifest, dict):
        raise ValueError("route receipt manifest is not a JSON object")
    plan = build_route_receipt_launch_plan(
        manifest,
        owner_tui=args.launch_owner,
        prepare_sink=args.prepare_route_receipt_sink,
    )
    markdown = render_route_receipt_launch_plan_markdown(plan)
    args.output_route_receipt_launch_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_route_receipt_launch_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_route_receipt_launch_json.write_text(
        json.dumps(plan, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    args.output_route_receipt_launch_md.write_text(markdown, encoding="utf-8")
    return plan


def main() -> int:
    args = parse_args()
    flow_plan: dict[str, Any] | None = None
    receipt_manifest: dict[str, Any] | None = None
    cutover_report: dict[str, Any] | None = None
    if args.flow_plan_only:
        flow_plan = _write_flow_plan_artifacts(args)
        if args.print_md:
            print(render_flow_canary_plan_markdown(flow_plan))
        else:
            print(f"wrote {args.output_flow_plan_json}")
            print(f"wrote {args.output_flow_plan_md}")
            print(json.dumps(flow_plan.get("summary", {}), indent=2, sort_keys=True))
        return 0
    if args.route_receipt_manifest_only:
        receipt_manifest = _write_route_receipt_manifest_artifacts(args)
        if args.print_md:
            print(render_route_receipt_manifest_markdown(receipt_manifest))
        else:
            print(f"wrote {args.output_route_receipt_manifest_json}")
            print(f"wrote {args.output_route_receipt_manifest_md}")
            print(
                json.dumps(
                    receipt_manifest.get("summary", {}),
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if args.route_receipt_launch_plan_only:
        launch_plan = _write_route_receipt_launch_artifacts(args)
        if args.print_md:
            print(render_route_receipt_launch_plan_markdown(launch_plan))
        else:
            print(f"wrote {args.output_route_receipt_launch_json}")
            print(f"wrote {args.output_route_receipt_launch_md}")
            print(
                json.dumps(
                    {
                        "owner_tui": launch_plan.get("owner_tui"),
                        "launch_status": launch_plan.get("launch_status"),
                        "receipt_path": launch_plan.get("receipt_path"),
                        "live_mutation_performed": launch_plan.get(
                            "live_mutation_performed"
                        ),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if args.harvest_route_receipts_only:
        harvest_report = _write_route_receipt_harvest_artifacts(args)
        if args.print_md:
            print(render_route_receipt_harvest_markdown(harvest_report))
        else:
            print(f"wrote {args.output_route_receipt_harvest_json}")
            print(f"wrote {args.output_route_receipt_harvest_md}")
            print(
                json.dumps(
                    harvest_report.get("summary", {}),
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if args.cutover_readiness_only:
        cutover_report = _write_cutover_readiness_artifacts(args)
        if args.print_md:
            print(render_cutover_readiness_markdown(cutover_report))
        else:
            print(f"wrote {args.output_cutover_readiness_json}")
            print(f"wrote {args.output_cutover_readiness_md}")
            print(
                json.dumps(cutover_report.get("summary", {}), indent=2, sort_keys=True)
            )
        return 0

    targets = _select_targets(args.targets)
    loop_count = max(1, args.loop_count)
    if args.source_json:
        statuses = load_status_source(args.source_json)
        source = str(args.source_json)
        report = build_report(
            statuses,
            source=source,
            mode=args.mode,
            fast_loop_interval_seconds=args.fast_loop_interval_seconds,
            max_changed_tickets_per_cycle=args.max_changed_tickets_per_cycle,
            daily_budget_usd=args.daily_budget_usd,
        )
        reports = [report]
    else:
        source = f"live:{','.join(targets)}"
        reports = []
        for cycle in range(1, loop_count + 1):
            statuses = fetch_statuses(targets, args.timeout)
            report = build_report(
                statuses,
                source=source,
                mode=args.mode,
                fast_loop_interval_seconds=args.fast_loop_interval_seconds,
                max_changed_tickets_per_cycle=args.max_changed_tickets_per_cycle,
                daily_budget_usd=args.daily_budget_usd,
            )
            report["cycle"] = cycle
            reports.append(report)
            if cycle < loop_count and args.loop_interval > 0:
                time.sleep(args.loop_interval)
        report = reports[-1]
    markdown = render_markdown(report)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    args.output_md.write_text(markdown, encoding="utf-8")
    journal_path = args.output_journal_json
    if journal_path is None and loop_count > 1:
        journal_path = DEFAULT_OUTPUT_JOURNAL_JSON
    if journal_path is not None:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal_path.write_text(
            json.dumps(build_journal(reports), indent=2, sort_keys=True),
            encoding="utf-8",
        )
    if args.write_flow_plan:
        flow_plan = _write_flow_plan_artifacts(args)
    if args.write_route_receipt_manifest:
        receipt_manifest = _write_route_receipt_manifest_artifacts(args)
    if args.write_cutover_readiness:
        cutover_report = _write_cutover_readiness_artifacts(args)
    ticket_cost_path = None
    if args.ticket_id:
        ticket_record = build_ticket_cost_record(
            ticket_id=args.ticket_id,
            actor=args.ticket_actor,
            source_kind="work_loop_canary",
            source_ref=str(args.output_json),
            architecture_mode=args.mode,
            runtime=args.ticket_runtime,
            model=args.ticket_model,
            service_tier=args.ticket_service_tier,
            price_basis=args.ticket_price_basis,
            input_tokens=args.ticket_input_tokens,
            cached_input_tokens=args.ticket_cached_input_tokens,
            output_tokens=args.ticket_output_tokens,
            reasoning_output_tokens=args.ticket_reasoning_output_tokens,
            total_tokens=args.ticket_total_tokens,
            usage_event_count=0,
            notes=args.ticket_notes,
            metadata={
                "report_schema": report.get("schema"),
                "summary": report.get("summary", {}),
                "targets": list(targets),
                "cost_basis": report.get("cost_basis", {}),
                "dry_run_only": True,
            },
        )
        append_ticket_cost_record(args.ticket_cost_ledger_jsonl, ticket_record)
        ticket_cost_path = args.ticket_cost_ledger_jsonl
    if args.print_md:
        print(markdown)
    else:
        print(f"wrote {args.output_json}")
        print(f"wrote {args.output_md}")
        if journal_path is not None:
            print(f"wrote {journal_path}")
        if flow_plan is not None:
            print(f"wrote {args.output_flow_plan_json}")
            print(f"wrote {args.output_flow_plan_md}")
        if receipt_manifest is not None:
            print(f"wrote {args.output_route_receipt_manifest_json}")
            print(f"wrote {args.output_route_receipt_manifest_md}")
        if cutover_report is not None:
            print(f"wrote {args.output_cutover_readiness_json}")
            print(f"wrote {args.output_cutover_readiness_md}")
        if ticket_cost_path is not None:
            print(f"wrote {ticket_cost_path}")
        print(json.dumps(report.get("summary", {}), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
