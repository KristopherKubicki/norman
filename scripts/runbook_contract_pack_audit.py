#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from runbook_hybrid_architecture_audit import (
    DEFAULT_MIRROR_ROOT,
    analyze_runbook,
    iter_runbook_paths,
    load_runbook_tiers,
)


BUCKET_KEYWORDS: dict[str, tuple[str, ...]] = {
    "use_when": (
        "use when",
        "trigger",
        "symptom",
        "applies",
        "scenario",
        "problem",
        "ticket",
    ),
    "required_evidence": (
        "evidence",
        "proof",
        "screenshot",
        "count",
        "counts",
        "audit",
        "csv",
        "rows",
        "log",
        "logs",
        "artifact",
    ),
    "allowed_reads": (
        "read",
        "query",
        "list",
        "inspect",
        "check",
        "status",
        "dry-run",
        "capture",
        "verify",
    ),
    "authority_gates": (
        "approval",
        "approved",
        "confirm",
        "explicit",
        "operator",
        "owner",
        "gate",
        "must not",
        "do not",
    ),
    "success_criteria": (
        "success",
        "done",
        "close",
        "complete",
        "resolved",
        "verify",
        "validated",
        "ready",
    ),
}


def estimate_tokens(text: str) -> int:
    clean = str(text or "")
    if not clean.strip():
        return 0
    return max(1, math.ceil(len(clean) / 4))


def _clean_line(value: str, *, limit: int = 180) -> str:
    clean = re.sub(r"\s+", " ", str(value or "")).strip(" -\t")
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "..."


def _candidate_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = _clean_line(raw)
        if not line or line.startswith("#"):
            continue
        if len(line) < 12:
            continue
        lines.append(line)
    if len(lines) < 8:
        chunks = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text))
        lines.extend(_clean_line(chunk) for chunk in chunks if len(chunk.strip()) >= 24)
    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(line)
    return deduped


def _bucket_lines(text: str, bucket: str, *, limit: int = 6) -> list[str]:
    keywords = BUCKET_KEYWORDS[bucket]
    matches: list[str] = []
    for line in _candidate_lines(text):
        lower = line.lower()
        if any(keyword in lower for keyword in keywords):
            matches.append(line)
        if len(matches) >= limit:
            break
    return matches


def _commands(text: str, *, limit: int = 6) -> list[str]:
    commands: list[str] = []
    for match in re.finditer(r"`([^`\n]{4,160})`", text):
        value = match.group(1).strip()
        if not value or value.endswith(".md"):
            continue
        if re.search(r"\b(?:python|make|pytest|curl|aws|jq|sqlite3|rg|git)\b", value):
            commands.append(value)
        if len(commands) >= limit:
            break
    return commands


def render_pack_text(pack: dict[str, Any]) -> str:
    return json.dumps(pack, sort_keys=True, separators=(",", ":"))


def build_contract_pack(
    path: Path, root: Path, tiers: dict[str, str]
) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    finding = analyze_runbook(path, root, tiers)
    pack_body = {
        "runbook_id": finding.runbook_id,
        "title": finding.title,
        "tier": finding.tier,
        "domain": finding.domain,
        "complexity": finding.complexity,
        "signals": finding.signals,
        "use_when": _bucket_lines(text, "use_when"),
        "required_evidence": _bucket_lines(text, "required_evidence"),
        "allowed_reads": _bucket_lines(text, "allowed_reads"),
        "suggested_commands": _commands(text),
        "authority_gates": _bucket_lines(text, "authority_gates"),
        "blocked_worker_actions": finding.blocked_worker_actions,
        "cheap_worker_scope": finding.cheap_worker_scope,
        "success_criteria": _bucket_lines(text, "success_criteria"),
        "verifier_focus": [
            "confirm evidence covers the ticket trigger",
            "reject any unapproved authority use",
            "require artifact refs instead of raw log dumps",
            "final closeout remains owned by 5.5",
        ],
        "source_ref": str(path),
    }
    full_tokens = estimate_tokens(text)
    pack_tokens = estimate_tokens(render_pack_text(pack_body))
    saved_tokens = max(0, full_tokens - pack_tokens)
    saved_pct = round(saved_tokens / full_tokens * 100, 1) if full_tokens else 0.0
    return {
        "schema": "norman.runbook-contract-pack.v1",
        "runbook_id": finding.runbook_id,
        "title": finding.title,
        "path": str(path),
        "full_text_tokens": full_tokens,
        "contract_pack_tokens": pack_tokens,
        "saved_tokens": saved_tokens,
        "saved_pct": saved_pct,
        "pack_expands_context": pack_tokens > full_tokens,
        "recommended_architecture": finding.recommended_architecture,
        "estimated_cost_ratio_vs_solo_5_5": finding.estimated_cost_ratio_vs_solo_5_5,
        "contract_pack": pack_body,
    }


def build_report(root: Path) -> dict[str, Any]:
    tiers = load_runbook_tiers(root)
    packs = [
        build_contract_pack(path, root, tiers) for path in iter_runbook_paths(root)
    ]
    full_tokens = sum(int(pack["full_text_tokens"]) for pack in packs)
    pack_tokens = sum(int(pack["contract_pack_tokens"]) for pack in packs)
    saved_tokens = max(0, full_tokens - pack_tokens)
    by_complexity = Counter(str(pack["contract_pack"]["complexity"]) for pack in packs)
    by_architecture = Counter(str(pack["recommended_architecture"]) for pack in packs)
    return {
        "schema": "norman.runbook-contract-pack-audit.v1",
        "generated_at": int(time.time()),
        "source_root": str(root),
        "summary": {
            "runbook_count": len(packs),
            "full_text_tokens": full_tokens,
            "contract_pack_tokens": pack_tokens,
            "saved_tokens": saved_tokens,
            "saved_pct": round(saved_tokens / full_tokens * 100, 1)
            if full_tokens
            else 0.0,
            "average_pack_tokens": round(pack_tokens / len(packs), 1) if packs else 0.0,
            "under_1000_token_packs": sum(
                1 for pack in packs if int(pack["contract_pack_tokens"]) <= 1000
            ),
            "pack_expands_context_count": sum(
                1 for pack in packs if pack["pack_expands_context"]
            ),
            "by_complexity": dict(sorted(by_complexity.items())),
            "by_recommended_architecture": dict(sorted(by_architecture.items())),
        },
        "contract_fields": [
            "runbook_id",
            "title",
            "tier",
            "domain",
            "complexity",
            "signals",
            "use_when",
            "required_evidence",
            "allowed_reads",
            "suggested_commands",
            "authority_gates",
            "blocked_worker_actions",
            "cheap_worker_scope",
            "success_criteria",
            "verifier_focus",
            "source_ref",
        ],
        "packs": packs,
    }


def _cell(value: Any) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Runbook Contract Pack Audit",
        "",
        f"- Source root: `{report['source_root']}`",
        f"- Runbooks inspected: {summary['runbook_count']}",
        f"- Full-text tokens: {summary['full_text_tokens']:,}",
        f"- Contract-pack tokens: {summary['contract_pack_tokens']:,}",
        f"- Estimated saved tokens: {summary['saved_tokens']:,} ({summary['saved_pct']}%)",
        f"- Packs under 1,000 tokens: {summary['under_1000_token_packs']}",
        f"- Packs larger than source: {summary['pack_expands_context_count']}",
        "",
        "## Pack Matrix",
        "",
        "| ID | Title | Full Tok | Pack Tok | Saved | Saved % | Complexity | Architecture |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for pack in report["packs"]:
        contract = pack["contract_pack"]
        lines.append(
            "| {id} | {title} | {full:,} | {packed:,} | {saved:,} | {pct:.1f}% | {complexity} | {architecture} |".format(
                id=_cell(pack["runbook_id"]),
                title=_cell(pack["title"]),
                full=int(pack["full_text_tokens"]),
                packed=int(pack["contract_pack_tokens"]),
                saved=int(pack["saved_tokens"]),
                pct=float(pack["saved_pct"]),
                complexity=_cell(contract["complexity"]),
                architecture=_cell(pack["recommended_architecture"]),
            )
        )
    lines.extend(
        [
            "",
            "## Next Benchmark Use",
            "",
            "- Give the planner only the contract pack and source artifact refs first.",
            "- Let cheap workers expand only the `required_evidence` and `allowed_reads` fields.",
            "- Escalate to full runbook text only when the verifier reports missing trigger, boundary, or success criteria.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile local mirrored runbooks into compact contract packs."
    )
    parser.add_argument("--mirror-root", type=Path, default=DEFAULT_MIRROR_ROOT)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("/tmp/norman_tui_benchmarks/runbook_contract_packs.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("/tmp/norman_tui_benchmarks/runbook_contract_packs.md"),
    )
    parser.add_argument("--print-md", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args.mirror_root)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    markdown = render_markdown(report)
    args.output_md.write_text(markdown, encoding="utf-8")
    if args.print_md:
        print(markdown)
    else:
        print(f"wrote {args.output_json}")
        print(f"wrote {args.output_md}")
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
