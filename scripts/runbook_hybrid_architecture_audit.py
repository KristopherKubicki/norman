#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_MIRROR_ROOT = Path(
    "/home/kristopher/.codex-work/retail-control-plane-sync/control_plane"
)


SIGNAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "approval": ("approval", "approved", "confirm", "explicit confirmation"),
    "apply_or_write": (
        "--apply",
        "write",
        "mutation",
        "mutating",
        "update",
        "delete",
        "suppress",
        "merge",
        "import",
        "backfill",
    ),
    "irreversible": ("irreversible", "hard delete", "legal", "offboarding"),
    "public_surface": (
        "public surface",
        "customer-visible",
        "dashboard",
        "tmi",
        "quicksight",
        "api/export",
        "report",
        "screenshot",
    ),
    "access_security": (
        "access",
        "entitlement",
        "credential",
        "security",
        "vanta",
        "mcp",
        "approval tier",
    ),
    "source_pipeline": (
        "etl",
        "source",
        "ingestion",
        "parser",
        "webgoat",
        "gapi",
        "specmaster",
        "airflow",
    ),
    "research_evidence": (
        "evidence",
        "wayback",
        "external",
        "audit",
        "impact analysis",
        "root cause",
    ),
    "batch_numeric": (
        "csv",
        "ledger",
        "rows",
        "batch",
        "counts",
        "trendline",
        "variance",
        "matrix",
    ),
    "screen_steering": (
        "screenshot",
        "browser",
        "dashboard navigation",
        "visible",
        "capture",
    ),
}


META_POLICY_DOC_IDS = {
    "runbook-catalog",
    "runbook-owner-escalation-map",
    "runbook-qa-checklist",
    "runbook-routing-matrix",
    "runbook-ticket-tagging",
}


DOMAIN_BY_PREFIX: dict[str, str] = {
    "MP": "Data Operations",
    "MPR": "Data Operations",
    "IS": "Data Operations",
    "PDR": "Data Operations + Product",
    "DU": "Data Operations",
    "PH": "Data Operations + Crawling",
    "WPL": "Data Operations + Crawling",
    "HCL": "Data Operations",
    "BR": "Data Operations",
    "MID": "Data Operations + Data Engineering",
    "CEI": "Data Operations",
    "LOBM": "Data Operations",
    "SH": "Data Engineering",
    "EPF": "Data Engineering",
    "SI": "Data Engineering",
    "RDF": "Data Engineering",
    "SDC": "Data Engineering",
    "MRI": "Data Engineering",
    "DMR": "Data Science",
    "HRB": "Data Science",
    "TMD": "Data Science",
    "AAE": "Product + Security + SalesDesk",
    "CDH": "Customer Delivery + Data Ops",
    "PFG": "Product Engineering",
    "PSM": "Product + Customer Delivery",
    "SQC": "Research + Survey Ops",
    "S2B": "SalesDesk + Product + Data Ops",
    "S7": "SalesDesk + Delivery + Data Ops",
    "S8": "Compliance + Data Ops + SalesDesk",
    "IA": "Data Science playbook",
    "NDS": "Data Science playbook",
    "PS": "Data Science playbook",
    "NE": "Data Science playbook",
    "MC": "Data Science playbook",
    "MR": "Data Science playbook",
    "DA": "Data Science playbook",
}


@dataclass(frozen=True)
class RunbookFinding:
    runbook_id: str
    title: str
    tier: str
    domain: str
    path: str
    word_count: int
    signals: list[str]
    complexity: str
    solo_5_5_xhigh: str
    hybrid_prototype: str
    recommended_architecture: str
    cheap_worker_scope: list[str]
    blocked_worker_actions: list[str]
    estimated_cost_ratio_vs_solo_5_5: float
    safety_rationale: str


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _first_heading(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback.replace("_", " ").replace("-", " ").strip().title()


def _runbook_id(path: Path) -> str:
    stem = path.stem
    match = re.match(r"([A-Z0-9]+)_", stem)
    if match:
        return match.group(1)
    return re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower()


def _extract_backticked_filenames(readme: str, section_header: str) -> set[str]:
    lines = readme.splitlines()
    active = False
    names: set[str] = set()
    for line in lines:
        if section_header in line:
            active = True
            continue
        if active and line.startswith("## "):
            break
        if active and line.strip() == "" and names:
            break
        if active:
            names.update(re.findall(r"`([^`]+\.md)`", line))
    return names


def load_runbook_tiers(root: Path) -> dict[str, str]:
    readme_path = root / "runbooks" / "README.md"
    if not readme_path.exists():
        return {}
    readme = _read(readme_path)
    routed = _extract_backticked_filenames(
        readme, "Routed runbooks with canonical Jira defaults in-repo:"
    )
    mirrored = _extract_backticked_filenames(
        readme, "Mirrored Data Science playbooks (not currently routed):"
    )
    tiers: dict[str, str] = {name: "canonical-or-routed" for name in routed}
    tiers.update({name: "mirrored-playbook" for name in mirrored})
    return tiers


def iter_runbook_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    runbooks_dir = root / "runbooks"
    docs_dir = root / "docs"
    if runbooks_dir.exists():
        paths.extend(
            p
            for p in sorted(runbooks_dir.glob("*.md"))
            if p.name not in {"README.md", "templates_and_examples.md"}
        )
    if docs_dir.exists():
        paths.extend(sorted(docs_dir.glob("*runbook*.md")))
        for extra in (
            "stage8_entitlement_offboarding.md",
            "public_surface_release_gate.md",
        ):
            p = docs_dir / extra
            if p.exists():
                paths.append(p)
    deduped: dict[str, Path] = {str(p): p for p in paths}
    return list(deduped.values())


def detect_signals(text: str) -> list[str]:
    lower = text.lower()
    found = [
        signal
        for signal, keywords in SIGNAL_KEYWORDS.items()
        if any(keyword.lower() in lower for keyword in keywords)
    ]
    return sorted(found)


def classify_complexity(runbook_id: str, signals: list[str], text: str) -> str:
    if runbook_id in META_POLICY_DOC_IDS:
        return "T2 workflow repair"
    lower = text.lower()
    if "irreversible" in signals or (
        "access_security" in signals
        and any(k in lower for k in ("offboarding", "credential", "vanta"))
    ):
        return "T4 guarded live authority"
    if "apply_or_write" in signals and (
        "approval" in signals
        or "public_surface" in signals
        or "source_pipeline" in signals
    ):
        return "T3 data/admin preflight"
    if "public_surface" in signals or "source_pipeline" in signals:
        return "T2 workflow repair"
    if "research_evidence" in signals or "batch_numeric" in signals:
        return "T1 evidence cleanup"
    return "T1 evidence cleanup"


def classify_tier(path: Path, tiers: dict[str, str], root: Path) -> str:
    if path.parent.name == "docs":
        return "operational-support"
    return tiers.get(path.name, "operational-support")


def architecture_for(
    complexity: str, signals: list[str]
) -> tuple[str, str, str, float, list[str], list[str], str]:
    cheap_scope = [
        "extract evidence",
        "normalize checklist/table rows",
        "draft strict JSON handoff",
    ]
    blocked = [
        "live apply/delete/restart",
        "credential inspection",
        "customer-facing final answer",
    ]
    if complexity.startswith("T4"):
        return (
            "strong: handles full runbook, but must still stop at human approval gates",
            "limited: local/cheap worker may prepare evidence only; 5.5 owns every decision",
            "solo-5.5-xhigh-for-decision; hybrid-only-for-evidence",
            0.82,
            cheap_scope,
            [*blocked, "access or entitlement mutation", "irreversible action"],
            "T4 runbooks carry access, legal, offboarding, or irreversible risk; delegation is useful only before authority gates.",
        )
    if complexity.startswith("T3"):
        return (
            "strong: safest end-to-end path for mutation planning and public-surface judgment",
            "good: 5.5 planner/final with cheap worker for preflight tables and evidence bundles",
            "hybrid-preflight-with-5.5-final",
            0.58,
            [*cheap_scope, "draft dry-run command checklist"],
            [*blocked, "claiming apply success without proof"],
            "T3 runbooks benefit from cheaper preprocessing, but 5.5 should verify mutation boundaries and closeout evidence.",
        )
    if complexity.startswith("T2"):
        return (
            "strong: reliable, but spends premium tokens on repeatable evidence sorting",
            "recommended: cheap worker drafts routing/evidence; 5.5 verifies ownership and final decision",
            "hybrid-recommended-with-5.5-verifier",
            0.43,
            [*cheap_scope, "classify route/owner/escalation candidates"],
            [*blocked, "owner reassignment without verifier"],
            "T2 work is mostly classification and evidence assembly, so hybrid saves tokens while keeping 5.5 on decisions.",
        )
    return (
        "works, but overpowered for routine evidence cleanup",
        "recommended: cheap worker can handle most drafting under strict JSON",
        "hybrid-recommended",
        0.32,
        [*cheap_scope, "summarize source refs"],
        blocked,
        "T1 work is read-only and repetitive; the hybrid lane is the better default if schema compliance holds.",
    )


def analyze_runbook(path: Path, root: Path, tiers: dict[str, str]) -> RunbookFinding:
    text = _read(path)
    runbook_id = _runbook_id(path)
    signals = detect_signals(text)
    complexity = classify_complexity(runbook_id, signals, text)
    solo, hybrid, recommended, ratio, cheap_scope, blocked, rationale = (
        architecture_for(complexity, signals)
    )
    return RunbookFinding(
        runbook_id=runbook_id,
        title=_first_heading(text, path.stem),
        tier=classify_tier(path, tiers, root),
        domain=DOMAIN_BY_PREFIX.get(runbook_id, "Operational support"),
        path=str(path),
        word_count=len(re.findall(r"\w+", text)),
        signals=signals,
        complexity=complexity,
        solo_5_5_xhigh=solo,
        hybrid_prototype=hybrid,
        recommended_architecture=recommended,
        cheap_worker_scope=cheap_scope,
        blocked_worker_actions=blocked,
        estimated_cost_ratio_vs_solo_5_5=ratio,
        safety_rationale=rationale,
    )


def build_report(root: Path) -> dict[str, Any]:
    tiers = load_runbook_tiers(root)
    findings = [analyze_runbook(path, root, tiers) for path in iter_runbook_paths(root)]
    by_complexity = Counter(f.complexity for f in findings)
    by_recommendation = Counter(f.recommended_architecture for f in findings)
    by_tier = Counter(f.tier for f in findings)
    return {
        "schema": "norman.runbook-hybrid-architecture-audit.v1",
        "generated_at": int(time.time()),
        "source_root": str(root),
        "source_basis": [
            "local mirror of Confluence runbooks/playbooks",
            "runbooks/README.md tier list",
            "docs/runbook_catalog.md and docs/runbook_routing_matrix.md context",
        ],
        "limitation": "No live Atlassian/Confluence tool was exposed in this session; this audit uses the local mirror.",
        "summary": {
            "runbook_count": len(findings),
            "by_complexity": dict(sorted(by_complexity.items())),
            "by_recommendation": dict(sorted(by_recommendation.items())),
            "by_tier": dict(sorted(by_tier.items())),
        },
        "findings": [asdict(finding) for finding in findings],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Runbook Hybrid Architecture Audit",
        "",
        f"- Source root: `{report['source_root']}`",
        f"- Runbooks inspected: {report['summary']['runbook_count']}",
        f"- Limitation: {report['limitation']}",
        "",
        "## Summary",
        "",
        "### By Complexity",
        "",
    ]
    for key, value in report["summary"]["by_complexity"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "### By Recommendation", ""])
    for key, value in report["summary"]["by_recommendation"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Runbook Matrix",
            "",
            "| ID | Title | Tier | Domain | Complexity | Recommended | Cost Ratio | Signals |",
            "|---|---|---|---|---|---|---:|---|",
        ]
    )
    for item in report["findings"]:
        lines.append(
            "| {id} | {title} | {tier} | {domain} | {complexity} | {rec} | {ratio:.2f} | {signals} |".format(
                id=item["runbook_id"],
                title=item["title"].replace("|", "/"),
                tier=item["tier"],
                domain=item["domain"],
                complexity=item["complexity"],
                rec=item["recommended_architecture"],
                ratio=item["estimated_cost_ratio_vs_solo_5_5"],
                signals=", ".join(item["signals"]) or "-",
            )
        )
    lines.extend(
        [
            "",
            "## Architecture Notes",
            "",
            "- Solo 5.5 xhigh is the safest all-way path, especially for T3/T4 runbooks, but it spends premium reasoning on repeatable evidence extraction.",
            "- Hybrid is recommended only when 5.5 writes the contract, cheap workers stay inside read-only or bounded preflight scope, and 5.5 verifies/finalizes.",
            "- Cheap workers must not claim live apply/delete/restart, inspect credentials, or own customer-facing closeout language.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit local Confluence runbook mirrors against hybrid architecture prototypes."
    )
    parser.add_argument("--mirror-root", type=Path, default=DEFAULT_MIRROR_ROOT)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args()

    report = build_report(args.mirror_root)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"wrote {args.output_json}")
    if args.output_md:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(render_markdown(report), encoding="utf-8")
        print(f"wrote {args.output_md}")
    if not args.output_json and not args.output_md:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
