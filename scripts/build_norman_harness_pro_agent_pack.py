#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACK_DIR = REPO_ROOT / "tmp" / "pro_agent_norman_harness_pack"
DEFAULT_EVIDENCE_ROOT = Path("/tmp/norman_tui_benchmarks")
DEFAULT_SOURCE_PROMPT = (
    DEFAULT_PACK_DIR / "source_prompt" / "codex_5_4_vs_5_5_xhigh_notes.txt"
)

SCRIPT_FILES = (
    "AGENTS.md",
    "Makefile",
    "app/app_routes.py",
    "app/static/css/styles.css",
    "app/static/js/home.js",
    "app/static/js/messages_log.js",
    "app/static/js/systems.js",
    "app/static/textures/tui_microtexture_reference.json",
    "app/templates/base.html",
    "app/templates/index.html",
    "app/templates/messages_log.html",
    "docs/work_bot_system_access.md",
    "scripts/agent_console_template/agent_console_launch.sh",
    "scripts/agent_console_template/agent_console_supervisor.sh",
    "scripts/agent_console_template/prompts/control-plane.txt",
    "scripts/agent_console_template/prompts/diamond-roc.txt",
    "scripts/agent_console_template/prompts/emerald-canopy.txt",
    "scripts/agent_console_template/prompts/scout.txt",
    "scripts/bbs_doctor.py",
    "scripts/bbs_janitor.py",
    "scripts/build_norman_harness_pro_agent_pack.py",
    "scripts/capture_tui_visual_states.py",
    "scripts/norman_bot_prime_start.sh",
    "scripts/norman_codex_launch.sh",
    "scripts/norman_codex_web.py",
    "scripts/agent_console_template/agent_console_web.py",
    "scripts/render_norman_bot_proxy_caddy.py",
    "scripts/runbook_hybrid_architecture_audit.py",
    "scripts/sync_agent_console_template.py",
    "scripts/sync_tui_microtextures.py",
    "scripts/systemd/norman-agent-console-sync-local.path",
    "scripts/systemd/norman-agent-console-sync-local.service",
    "scripts/systemd/norman-agent-console-sync-local.timer",
    "scripts/systemd/norman-bbs-doctor.path",
    "scripts/systemd/norman-bbs-doctor.service",
    "scripts/systemd/norman-bbs-doctor.timer",
    "scripts/tui_provider_readiness_benchmark.py",
    "scripts/tui_bedrock_shortstop_benchmark.py",
    "scripts/tui_auto_mode_benchmark.py",
    "scripts/paired_hybrid_replay_benchmark.py",
    "scripts/local_model_skill_floor.py",
    "scripts/work_loop_canary.py",
    "scripts/work_domain_skill_benchmark.py",
    "scripts/historic_shadow_planner_route_benchmark.py",
    "scripts/gaphelp_ticket_loop_shadow.py",
    "scripts/ticket_token_cost_ledger.py",
    "scripts/route_policy_drift_lint.py",
)

TEST_FILES = (
    "tests/test_build_norman_harness_pro_agent_pack.py",
    "tests/test_norman_codex_model_settings.py",
    "tests/test_agent_console_template_masking.py",
    "tests/test_sync_agent_console_template.py",
    "tests/test_tui_provider_readiness_benchmark.py",
    "tests/test_tui_bedrock_shortstop_benchmark.py",
    "tests/test_tui_auto_mode_benchmark.py",
    "tests/test_paired_hybrid_replay_benchmark.py",
    "tests/test_local_model_skill_floor.py",
    "tests/test_work_loop_canary.py",
    "tests/test_work_domain_skill_benchmark.py",
    "tests/test_historic_shadow_planner_route_benchmark.py",
    "tests/test_gaphelp_ticket_loop_shadow.py",
    "tests/test_ticket_token_cost_ledger.py",
    "tests/test_route_policy_drift_lint.py",
)

FIXTURE_FILES = (
    (
        "db/paired_hybrid_replay_cases.json",
        "data/fixtures/paired_hybrid_replay_cases.json",
    ),
    (
        "db/tui_context_shadow_benchmark_sample.json",
        "data/fixtures/tui_context_shadow_benchmark_sample.json",
    ),
    (
        "db/tui_quality_benchmark_cases.json",
        "data/fixtures/tui_quality_benchmark_cases.json",
    ),
    (
        "db/tui_quality_shadow_answers.example.json",
        "data/fixtures/tui_quality_shadow_answers.example.json",
    ),
)

LIVE_EVIDENCE_FILES = (
    "tui_cutover_readiness.json",
    "tui_cutover_readiness.md",
    "tui_route_receipt_harvest.json",
    "tui_route_receipt_harvest.md",
    "tui_route_receipt_manifest.json",
    "tui_route_receipt_manifest.md",
    "tui_route_receipt_launch_plan.json",
    "tui_route_receipt_launch_plan.md",
    "historic_shadow_planner_route_benchmark.json",
    "historic_shadow_planner_route_benchmark.md",
    "ollama_sense_live.json",
    "ollama_sense_live.md",
    "vllm_sense_live.json",
    "vllm_sense_live.md",
)
OLD_FAILURE_REPORT_GLOBS = (
    "*shortstop*.md",
    "*short-stop*.md",
    "*low_yield*.md",
    "*low-yield*.md",
)
OLD_FAILURE_SUMMARY_GLOBS = (
    "*shortstop*.json",
    "*short-stop*.json",
    "*low_yield*.json",
    "*low-yield*.json",
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _copy_file(source_rel: str, dest_rel: str, pack_dir: Path) -> Path:
    source = REPO_ROOT / source_rel
    if not source.exists() and dest_rel.startswith("data/fixtures/"):
        source = REPO_ROOT.parent / dest_rel
    if not source.exists():
        raise FileNotFoundError(source)
    dest = pack_dir / dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return dest


def _write_text(pack_dir: Path, rel: str, body: str) -> Path:
    path = pack_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _read_json(path: Path) -> object | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _copy_evidence_file(source: Path, dest_rel: str, pack_dir: Path) -> Path | None:
    if not source.exists() or not source.is_file():
        return None
    dest = pack_dir / dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return dest


def copy_live_evidence(pack_dir: Path, evidence_root: Path) -> list[Path]:
    written: list[Path] = []
    for rel in LIVE_EVIDENCE_FILES:
        copied = _copy_evidence_file(
            evidence_root / rel,
            f"live_evidence/{rel}",
            pack_dir,
        )
        if copied is not None:
            written.append(copied)

    receipt_dir = evidence_root / "route_receipts"
    if receipt_dir.exists():
        for source in sorted(receipt_dir.glob("*.jsonl")):
            copied = _copy_evidence_file(
                source,
                f"live_evidence/route_receipts/{source.name}",
                pack_dir,
            )
            if copied is not None:
                written.append(copied)
    for pattern in OLD_FAILURE_REPORT_GLOBS:
        for source in sorted(evidence_root.glob(pattern)):
            copied = _copy_evidence_file(
                source,
                f"live_evidence/old_failures/{source.name}",
                pack_dir,
            )
            if copied is not None:
                written.append(copied)
    return written


def route_policy(generated_at: str) -> dict[str, object]:
    return {
        "schema": "norman.pro-agent-route-policy.v1",
        "generated_at": generated_at,
        "operator_goal": (
            "Make GPT-5.4 carry long workflows with stability close to GPT-5.5, "
            "reserving GPT-5.5 for rare final-authority/tiebreaker work."
        ),
        "work_special_default": {
            "model": "openai.gpt-5.4",
            "service_tier": "default",
            "provider": "Bedrock",
            "failover_order": [
                "Bedrock openai.gpt-5.4 primary region",
                "Bedrock openai.gpt-5.4 secondary region",
                "Bedrock openai.gpt-5.4 tertiary region",
                "OpenAI direct gpt-5.4",
            ],
        },
        "netops_non_work_default": {
            "model": "gpt-5.4",
            "service_tier": "flex",
            "provider": "OpenAI direct",
            "switchable_models": ["gpt-5.4", "gpt-5.5"],
            "bedrock_default_allowed": False,
        },
        "use_gpt_5_5_when": [
            "high-authority final decision",
            "ambiguous deploy or rollback decision",
            "security-sensitive judgment",
            "frontier/tiebreaker after GPT-5.4 evidence is insufficient",
            "long workflow where route receipts show GPT-5.4 failed objective quality gates",
        ],
        "avoid_gpt_5_5_when": [
            "status checks",
            "simple health probes",
            "bounded file edits",
            "quick diffs",
            "routine tests",
            "ordinary summarization",
            "cheap extraction or classification work",
        ],
    }


def readme(generated_at: str) -> str:
    return f"""# Norman Harness Pro Agent Pack

Generated: {generated_at}

Purpose: give a Pro-level reviewer enough safe local evidence to improve the
Norman TUI harness so GPT-5.4 can carry long workflows with fewer GPT-5.5
escalations.

This pack excludes auth files, env tokens, live logs with secrets, Codex homes,
and remote machine state dumps. It contains code, fixtures, generated benchmark
reports, live route-receipt evidence when available, and the operator's pasted
model-comparison notes when provided.

## What To Ask The Pro Agent

Use `brief/PRO_AGENT_PROMPT.md` as the main prompt.
Use `brief/LIVE_HANDOFF.md` for the current implementation/deployment status.

## Repro Commands

From this pack root:

```bash
cd code
python -m pytest -q tests
python scripts/paired_hybrid_replay_benchmark.py --output-json /tmp/paired.json --output-md /tmp/paired.md
python scripts/route_policy_drift_lint.py --root .
```

The paired replay script resolves fixtures from either `code/db/` or
`data/fixtures/`, so the pack does not need repo-specific symlinks.
"""


def pro_prompt() -> str:
    return """# Prompt For Pro Agent

You are reviewing the Norman TUI harness. The operator's goal is to make
GPT-5.4 carry long workflows almost as reliably as GPT-5.5, while reserving
GPT-5.5 for rare final-authority or tiebreaker work.

Prioritize concrete changes to routing, receipts, checkpoints, promotion gates,
resume behavior, and route-policy drift detection. Treat generated benchmark
reports as dry-run/shadow hypotheses unless a route receipt proves a live run.

Constraints:

- Default work-special path should stay GPT-5.4-first.
- NetOps and non-work accounts should not receive Bedrock defaults unless
  explicitly provisioned.
- GPT-5.5 should not be used for ordinary status checks, simple diffs, quick
  health probes, or bounded file edits.
- GPT-5.5 may be used for high-authority final decisions, ambiguous rollback or
  deploy calls, security-sensitive judgment, or when GPT-5.4/hybrid evidence
  fails.
- Any live deploy, secret read, destructive action, external send, or
  billing-impacting change must stay approval-gated.

Specific questions to answer:

1. Is the route receipt append-chain sufficient for promotion evidence, or
   should it add HMAC/signatures before broader rollout?
2. Are the wave-1 gates right: 50 live receipts or 24 hours, zero boundary
   violations, validator pass >= 98%, manual override <= 5%, fallback <= 15%,
   and cost savings >= 25%?
3. What bad-route corpus should be added for short operator commands like
   `status?`, `continue`, `go ahead`, `restart if needed`, and `undo`?
4. What should the next harness investment be after live receipt capture:
   dashboarding, p95 budget gates, 5.5 save-rate KPI, or worker contracts?
"""


def status_and_drift() -> str:
    return """# Status And Drift Notes

- Current policy target: local/no-model fast path -> cheap bounded worker ->
  GPT-5.4 verifier/heavy-lift -> GPT-5.5 final authority only when needed.
- Treat reports as dry-run evidence unless a live route receipt proves the
  requested and effective route.
- Run `code/scripts/route_policy_drift_lint.py` to find old 5.5-default wording
  in reports, prompts, tests, or scripts.
"""


def _summary_from_cutover(evidence_root: Path) -> dict[str, object]:
    raw = _read_json(evidence_root / "tui_cutover_readiness.json")
    if not isinstance(raw, dict):
        return {}
    summary = raw.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    market = {}
    for target in raw.get("targets", []):
        if isinstance(target, dict) and target.get("owner_tui") == "market-sizing":
            market = target
            break
    return {
        "readiness": raw.get("readiness"),
        "summary": summary,
        "market_sizing": market,
    }


def _first_live_receipt(evidence_root: Path) -> dict[str, object]:
    receipt_path = evidence_root / "route_receipts" / "market-sizing.jsonl"
    if not receipt_path.exists():
        return {}
    try:
        for line in receipt_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                raw = json.loads(line)
                return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def live_handoff(generated_at: str, evidence_root: Path) -> str:
    cutover = _summary_from_cutover(evidence_root)
    summary = cutover.get("summary") if isinstance(cutover.get("summary"), dict) else {}
    market = (
        cutover.get("market_sizing")
        if isinstance(cutover.get("market_sizing"), dict)
        else {}
    )
    metrics = market.get("metrics") if isinstance(market.get("metrics"), dict) else {}
    blockers = (
        market.get("blockers") if isinstance(market.get("blockers"), list) else []
    )
    next_actions = (
        market.get("next_actions")
        if isinstance(market.get("next_actions"), list)
        else []
    )
    receipt = _first_live_receipt(evidence_root)
    receipt_hash = str(receipt.get("receipt_hash") or "")
    receipt_hash_short = receipt_hash[:16] if receipt_hash else "missing"

    return f"""# Live Handoff

Generated: {generated_at}

## Current State

- Work-special target policy: GPT-5.4-first; GPT-5.5 only for final authority,
  tiebreaker, safety boundary, or failed 5.4 evidence gate.
- Receipt storage target: `/var/lib/norman/route_receipts/<owner>.jsonl`, with
  append-chain fields `previous_receipt_hash` and `receipt_hash`.
- Latest live evidence in this pack is under `live_evidence/`.
- No auth tokens, env files, Codex homes, or remote state dumps are intentionally
  included.

## Live Evidence Summary

- Cutover readiness: {cutover.get("readiness") or "missing"}
- Receipt count: {summary.get("receipt_count", "missing")}
- Route receipt chain issues: {summary.get("route_receipt_chain_issue_count", "missing")}
- Ready targets: {summary.get("ready_target_count", "missing")}
- Blocked targets: {summary.get("blocked_target_count", "missing")}
- Historic route benchmark gate: {summary.get("historic_route_benchmark_gate", "missing")}
- Market-sizing receipt count: {metrics.get("receipt_count", "missing")}
- Market-sizing validator pass rate: {metrics.get("validator_pass_rate", "missing")}
- Market-sizing blocker(s): {", ".join(str(item) for item in blockers) or "none recorded"}
- Market-sizing next action(s): {", ".join(str(item) for item in next_actions) or "none recorded"}

## First Live Receipt Snapshot

- Owner: {receipt.get("owner_tui", "missing")}
- Intent: {receipt.get("operator_intent_class", "missing")}
- Authority: {receipt.get("authority_class", "missing")}
- Mutation risk: {receipt.get("mutation_risk", "missing")}
- Requested model: {receipt.get("requested_model", "missing")}
- Effective model: {receipt.get("effective_model", "missing")}
- Requested service tier: {receipt.get("requested_service_tier", "missing")}
- Effective service tier: {receipt.get("effective_service_tier", "missing")}
- Validator gate: {receipt.get("validator_gate", "missing")}
- Receipt hash prefix: {receipt_hash_short}

## What To Review Next

1. Confirm whether the append-chain is enough for wave-1 promotion evidence or
   whether HMAC/signature support should be mandatory first.
2. Review the current wave-1 cutover gates and whether market-sizing needs 50
   receipts, 24 hours, or both before promotion.
3. Review the control-router and turn-envelope shape in
   `code/scripts/norman_codex_web.py`.
4. Review the deploy/sync behavior in
   `code/scripts/sync_agent_console_template.py`, especially non-work NetOps
   protection from Bedrock defaults.
5. Propose the next narrow implementation slice for live receipts, p95 budget
   gates, bad-route corpus, and GPT-5.5 save-rate measurement.
"""


def _shortstop_summary_reports(evidence_root: Path) -> list[Path]:
    seen: set[Path] = set()
    reports: list[Path] = []
    for pattern in OLD_FAILURE_SUMMARY_GLOBS:
        for path in sorted(evidence_root.glob(pattern)):
            if path not in seen and path.is_file():
                reports.append(path)
                seen.add(path)
    return reports


def _category_summary(categories: object) -> str:
    if not isinstance(categories, dict) or not categories:
        return "missing"
    return ", ".join(f"{key}={value}" for key, value in sorted(categories.items()))


def failure_packet(generated_at: str, evidence_root: Path) -> str:
    reports = _shortstop_summary_reports(evidence_root)
    lines = [
        "# Failure Packet",
        "",
        f"Generated: {generated_at}",
        "",
        "Purpose: compact old-log evidence for improving the hybrid optimizer "
        "without bundling raw SQLite/history logs or auth material.",
        "",
    ]
    if not reports:
        lines.extend(
            [
                "## Old-Log Evidence",
                "",
                "- No short-stop/low-yield benchmark JSON was found in the evidence root.",
                "- Generate one with `scripts/tui_bedrock_shortstop_benchmark.py` and place "
                "the JSON/Markdown output under the evidence root before rebuilding.",
                "",
            ]
        )
        return "\n".join(lines)

    lines.extend(["## Old-Log Evidence", ""])
    for path in reports:
        raw = _read_json(path)
        if not isinstance(raw, dict):
            lines.append(f"- `{path.name}`: unreadable JSON")
            continue
        summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
        turns = summary.get("turns", "missing")
        categories = _category_summary(summary.get("categories"))
        mechanisms = _category_summary(summary.get("mechanisms"))
        tui_parts: list[str] = []
        for item in summary.get("tuis", []):
            if not isinstance(item, dict):
                continue
            tui_parts.append(
                "{tui}: turns={turns}, output_pct={output_pct}, categories={categories}, mechanisms={mechanisms}".format(
                    tui=item.get("tui", "unknown"),
                    turns=item.get("turns", "missing"),
                    output_pct=item.get("output_token_pct", "missing"),
                    categories=_category_summary(item.get("categories")),
                    mechanisms=_category_summary(item.get("mechanisms")),
                )
            )
        lines.append(
            f"- `{path.name}`: turns={turns}; categories={categories}; mechanisms={mechanisms}"
        )
        if tui_parts:
            lines.append(f"  - TUI summaries: {'; '.join(tui_parts[:4])}")
        examples = raw.get("examples") if isinstance(raw.get("examples"), list) else []
        for example in examples[:3]:
            if not isinstance(example, dict):
                continue
            reasons = (
                example.get("reasons")
                if isinstance(example.get("reasons"), list)
                else []
            )
            lines.append(
                "  - Example: category={category}; model={model}; seconds={seconds}; "
                "reasons={reasons}".format(
                    category=example.get("category", "unknown"),
                    model=example.get("model", "unknown"),
                    seconds=example.get("duration_seconds", "unknown"),
                    reasons=", ".join(str(item) for item in reasons) or "none",
                )
            )
    lines.extend(
        [
            "",
            "## Harness Implications",
            "",
            "- Treat high short-stop and low-yield counts as promotion blockers until "
            "route receipts show the optimized path completes work, not just drafts intent.",
            "- Add bad-route/retry cases from these categories before allowing broader "
            "hybrid promotion.",
            "- Keep old-log packet evidence summary-only unless an operator explicitly "
            "approves sharing raw logs.",
            "",
        ]
    )
    return "\n".join(lines)


def manifest(paths: list[Path], pack_dir: Path) -> str:
    rels = sorted(str(path.relative_to(pack_dir)) for path in paths)
    lines = ["# Manifest", ""]
    for rel in rels:
        lines.append(f"- `{rel}`")
    return "\n".join(lines) + "\n"


def _run_report_command(args: list[str]) -> None:
    subprocess.run(args, cwd=REPO_ROOT, check=True)


def generate_reports(
    pack_dir: Path, python: str, evidence_root: Path = DEFAULT_EVIDENCE_ROOT
) -> list[Path]:
    reports = pack_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    commands = [
        [
            python,
            "scripts/tui_provider_readiness_benchmark.py",
            "--output-json",
            str(reports / "provider_readiness.json"),
            "--output-md",
            str(reports / "provider_readiness.md"),
        ],
        [
            python,
            "scripts/tui_provider_readiness_benchmark.py",
            "--dump-prompts",
            str(reports / "provider_readiness_prompts.json"),
        ],
        [
            python,
            "scripts/paired_hybrid_replay_benchmark.py",
            "--output-json",
            str(reports / "paired_hybrid_replay.json"),
            "--output-md",
            str(reports / "paired_hybrid_replay.md"),
        ],
        [
            python,
            "scripts/tui_auto_mode_benchmark.py",
            "--output-json",
            str(reports / "auto_mode.json"),
            "--output-md",
            str(reports / "auto_mode.md"),
        ],
        [
            python,
            "scripts/work_domain_skill_benchmark.py",
            "--output-json",
            str(reports / "work_domain_skill_matrix.json"),
            "--output-md",
            str(reports / "work_domain_skill_matrix.md"),
        ],
        [
            python,
            "scripts/local_model_skill_floor.py",
            "--skill-matrix-json",
            str(reports / "work_domain_skill_matrix.json"),
            "--ollama-sense-json",
            str(evidence_root / "ollama_sense_live.json"),
            "--vllm-sense-json",
            str(evidence_root / "vllm_sense_live.json"),
            "--output-json",
            str(reports / "local_model_skill_floors.json"),
            "--output-md",
            str(reports / "local_model_skill_floors.md"),
        ],
        [
            python,
            "scripts/work_loop_canary.py",
            "--flow-plan-only",
            "--skill-matrix-json",
            str(reports / "work_domain_skill_matrix.json"),
            "--output-flow-plan-json",
            str(reports / "tui_flow_canary_plan.json"),
            "--output-flow-plan-md",
            str(reports / "tui_flow_canary_plan.md"),
        ],
        [
            python,
            "scripts/route_policy_drift_lint.py",
            "--output-json",
            str(reports / "route_policy_drift_lint.json"),
            "--output-md",
            str(reports / "route_policy_drift_lint.md"),
        ],
    ]
    for command in commands:
        _run_report_command(command)
    return sorted(path for path in reports.iterdir() if path.is_file())


def write_sha256s(pack_dir: Path) -> Path:
    lines: list[str] = []
    for path in sorted(p for p in pack_dir.rglob("*") if p.is_file()):
        if path.name == "SHA256SUMS.txt":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(pack_dir)}")
    return _write_text(pack_dir, "SHA256SUMS.txt", "\n".join(lines) + "\n")


def write_zip(pack_dir: Path, zip_path: Path) -> Path:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(p for p in pack_dir.rglob("*") if p.is_file()):
            archive.write(path, path.relative_to(pack_dir.parent))
    return zip_path


def build_pack(
    pack_dir: Path,
    *,
    zip_path: Path | None,
    include_reports: bool,
    source_prompt: Path | None,
    python: str,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
) -> dict[str, object]:
    generated_at = _utc_stamp()
    source_prompt_text = ""
    source_prompt_path = source_prompt or DEFAULT_SOURCE_PROMPT
    if source_prompt_path and source_prompt_path.exists():
        source_prompt_text = source_prompt_path.read_text(encoding="utf-8")
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for rel in SCRIPT_FILES:
        written.append(_copy_file(rel, f"code/{rel}", pack_dir))
    for rel in TEST_FILES:
        written.append(_copy_file(rel, f"code/{rel}", pack_dir))
    for source_rel, dest_rel in FIXTURE_FILES:
        written.append(_copy_file(source_rel, dest_rel, pack_dir))

    written.append(_write_text(pack_dir, "README.md", readme(generated_at)))
    written.append(_write_text(pack_dir, "brief/PRO_AGENT_PROMPT.md", pro_prompt()))
    written.append(
        _write_text(pack_dir, "brief/STATUS_AND_DRIFT.md", status_and_drift())
    )
    written.append(
        _write_text(
            pack_dir, "brief/LIVE_HANDOFF.md", live_handoff(generated_at, evidence_root)
        )
    )
    written.append(
        _write_text(
            pack_dir,
            "brief/FAILURE_PACKET.md",
            failure_packet(generated_at, evidence_root),
        )
    )
    written.append(
        _write_text(
            pack_dir,
            "brief/ROUTE_POLICY.json",
            json.dumps(route_policy(generated_at), indent=2) + "\n",
        )
    )
    if source_prompt_text:
        written.append(
            _write_text(
                pack_dir,
                "source_prompt/codex_5_4_vs_5_5_xhigh_notes.txt",
                source_prompt_text,
            )
        )

    if include_reports:
        written.extend(generate_reports(pack_dir, python, evidence_root))
    written.extend(copy_live_evidence(pack_dir, evidence_root))

    manifest_path = _write_text(pack_dir, "MANIFEST.md", manifest(written, pack_dir))
    written.append(manifest_path)
    sha_path = write_sha256s(pack_dir)
    written.append(sha_path)

    zip_written = None
    if zip_path:
        zip_written = write_zip(pack_dir, zip_path)

    return {
        "schema": "norman.pro-agent-pack-build.v1",
        "pack_dir": str(pack_dir),
        "zip_path": str(zip_written) if zip_written else "",
        "file_count": len([p for p in pack_dir.rglob("*") if p.is_file()]),
        "include_reports": include_reports,
        "evidence_root": str(evidence_root),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the Norman Harness Pro Agent Pack."
    )
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    parser.add_argument(
        "--zip-path",
        type=Path,
        default=REPO_ROOT
        / "tmp"
        / f"norman_harness_pro_agent_pack_{_date_stamp()}.zip",
    )
    parser.add_argument("--no-zip", action="store_true")
    parser.add_argument("--skip-reports", action="store_true")
    parser.add_argument("--source-prompt", type=Path)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--python", default=sys.executable)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_pack(
        args.pack_dir,
        zip_path=None if args.no_zip else args.zip_path,
        include_reports=not args.skip_reports,
        source_prompt=args.source_prompt,
        python=args.python,
        evidence_root=args.evidence_root,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
