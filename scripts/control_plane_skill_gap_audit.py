#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from work_domain_skill_benchmark import build_report


DEFAULT_MIRROR_ROOT = Path(
    "/home/kristopher/.codex-work/retail-control-plane-sync/control_plane"
)
DEFAULT_OUTPUT_JSON = Path(
    "/tmp/norman_tui_benchmarks/control_plane_skill_gap_audit.json"
)
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_benchmarks/control_plane_skill_gap_audit.md")

SCRIPT_REF_RE = re.compile(r"`scripts/([^`]+?\.py)`")
RUNBOOK_ID_RE = re.compile(r"^([A-Z0-9]+)[_-]")


@dataclass(frozen=True)
class ScriptSkillGroup:
    group_id: str
    label: str
    patterns: tuple[str, ...]
    benchmark_domains: tuple[str, ...]
    expected_skill_keywords: tuple[str, ...]
    missing_skill_examples: tuple[str, ...]
    notes: str


SCRIPT_SKILL_GROUPS: tuple[ScriptSkillGroup, ...] = (
    ScriptSkillGroup(
        group_id="core_runbook_control",
        label="Core runbook/control-plane controllers",
        patterns=(
            "runbook_*.py",
            "ticket_turnkey.py",
            "critical_watchdog.py",
            "doctor.py",
            "new_session.py",
        ),
        benchmark_domains=("control-plane", "runbook-governance", "helpdesk"),
        expected_skill_keywords=("runbook", "script catalog", "safe action"),
        missing_skill_examples=(
            "runbook_runner table-driven dry-run",
            "critical watchdog SLA triage",
        ),
        notes="Core controllers need command-shape, dry-run, owner, and authority tests.",
    ),
    ScriptSkillGroup(
        group_id="gaphelp_apply_repairs",
        label="GapHelp apply/verify repair scripts",
        patterns=("apply_gaphelp*.py", "verify_gaphelp*.py"),
        benchmark_domains=("helpdesk", "control-plane", "data-fix"),
        expected_skill_keywords=("gaphelp", "ticket", "evidence", "close"),
        missing_skill_examples=(
            "one-off GAPHELP repair script classifier",
            "apply script postcheck/rollback pack",
        ),
        notes="Many one-off repairs should collapse into route, dry-run, apply-false, postcheck, and closeout skills.",
    ),
    ScriptSkillGroup(
        group_id="gapi_exact_repairs",
        label="GAPI exact repair/apply scripts",
        patterns=(
            "apply_gapi_*.py",
            "apply_*gapi*.py",
            "apply_*pricing*.py",
            "apply_*promo*.py",
            "apply_*branch*.py",
            "apply_*merge*.py",
            "apply_*rehome*.py",
            "cleanup_*.py",
        ),
        benchmark_domains=("data-fix", "data-pipelines", "helpdesk"),
        expected_skill_keywords=("mutation", "rollback", "backfill", "duplicate"),
        missing_skill_examples=(
            "exact row mutation gate",
            "postcheck reconciliation",
            "rollback CSV validation",
        ),
        notes="This is the highest-risk script family; most work should be lower-worker draft plus 5.4/5.5 gates.",
    ),
    ScriptSkillGroup(
        group_id="audit_qc",
        label="Audit/QC/analyze scripts",
        patterns=("audit_*.py", "analyze_*.py", "*_audit.py", "*_qc*.py"),
        benchmark_domains=("data-fix", "data-pipelines", "helpdesk"),
        expected_skill_keywords=("audit", "anomaly", "validator", "diff"),
        missing_skill_examples=("audit result taxonomy", "QC finding to runbook route"),
        notes="Good cheap-worker territory when outputs have schemas and row counts.",
    ),
    ScriptSkillGroup(
        group_id="webgoat_ecom",
        label="WebGOAT/ecom/source extraction",
        patterns=("*webgoat*.py", "ecom_*.py", "capture_retailer_category_count.py"),
        benchmark_domains=("webgoat", "hal-workflows", "data-pipelines"),
        expected_skill_keywords=("webgoat", "selector", "jmespath", "merchant"),
        missing_skill_examples=(
            "WebGOAT payload gate triage",
            "external denominator evidence packet",
        ),
        notes="Selectors are covered, but payload gates and denominator proof need more explicit cases.",
    ),
    ScriptSkillGroup(
        group_id="instore_panelbot_receipts",
        label="InStore, PanelBot, and receipts",
        patterns=("*instore*.py", "*panelbot*.py", "*receipt*.py", "gapinstore*.py"),
        benchmark_domains=("data-pipelines", "hal-workflows"),
        expected_skill_keywords=(
            "instore",
            "panelbot",
            "gapinstore",
            "receipt temporal",
            "receipt repair",
        ),
        missing_skill_examples=(
            "InStore source freshness triage",
            "PanelBot sibling/ecom corroboration",
            "receipt temporal alignment",
        ),
        notes="Benchmark now has this family, but specific data-quality submodes remain broad.",
    ),
    ScriptSkillGroup(
        group_id="planogram_ocr_dace",
        label="Planogram, OCR, and DACE cert",
        patterns=("*planogram*.py", "*ocr*.py", "*dace*.py", "*cert*.py"),
        benchmark_domains=("data-pipelines", "hal-workflows"),
        expected_skill_keywords=("planogram", "ocr", "dace", "cert"),
        missing_skill_examples=(
            "image extraction uncertainty grading",
            "cert queue stuck-post triage",
        ),
        notes="Covered at the handoff level; still needs more low-level cert failure cases.",
    ),
    ScriptSkillGroup(
        group_id="product_art_media",
        label="Product art/media/image recovery",
        patterns=("*product_art*.py", "*image*.py", "*media*.py", "*thumb*.py"),
        benchmark_domains=("data-pipelines", "hal-workflows"),
        expected_skill_keywords=("product-art", "image", "media"),
        missing_skill_examples=(
            "image URL preflight and dead-image hold",
            "sideload postcheck and timeout recovery",
        ),
        notes="Product-art queues are represented; image upload/sideload postchecks are still thin.",
    ),
    ScriptSkillGroup(
        group_id="smartphone_offer_cleanup",
        label="Smartphone, offer-mode, and carrier cleanup",
        patterns=("*smartphone*.py", "*phone_tablet*.py", "*carrier_offer*.py"),
        benchmark_domains=("data-pipelines", "data-fix"),
        expected_skill_keywords=("smartphone", "offer", "mutation gate"),
        missing_skill_examples=(
            "offer-mode proof classifier",
            "country/lane split clone validator",
        ),
        notes="Tier-1 target and mutation gate are covered; offer-mode proofs need more detail.",
    ),
    ScriptSkillGroup(
        group_id="provider_kpi_dashboard",
        label="Provider, KPI, dashboard, and TMI/QuickSight",
        patterns=(
            "*provider*.py",
            "kpi_*.py",
            "*dashboard*.py",
            "*tmi*.py",
            "*quicksight*.py",
        ),
        benchmark_domains=("data-pipelines", "hal-workflows", "helpdesk"),
        expected_skill_keywords=("provider", "kpi", "tmi", "dashboard"),
        missing_skill_examples=(
            "QuickSight ingestion proof classifier",
            "provider preflight contract failure route",
        ),
        notes="TMI proof is present; QuickSight/provider contract subcases should be expanded.",
    ),
    ScriptSkillGroup(
        group_id="cms_customer_salesdesk",
        label="CMS, customer deliverables, and SalesDesk lifecycle",
        patterns=(
            "*cms*.py",
            "*customer*.py",
            "*salesdesk*.py",
            "*stage7*.py",
            "*stage8*.py",
        ),
        benchmark_domains=("hal-workflows", "helpdesk", "control-plane"),
        expected_skill_keywords=("cms", "customer", "stage"),
        missing_skill_examples=(
            "customer deliverable health audit",
            "CMS editorial quality triage",
            "stage7/stage8 entitlement checklist",
        ),
        notes="Stage 7/8 is covered in helpdesk; CMS/customer deliverable skills are under-modeled.",
    ),
    ScriptSkillGroup(
        group_id="source_brightdata_wayback",
        label="Source, BrightData, Wayback, and public evidence",
        patterns=("*source*.py", "*brightdata*.py", "*wayback*.py", "*browser_pdp*.py"),
        benchmark_domains=("webgoat", "data-pipelines", "helpdesk"),
        expected_skill_keywords=("source", "evidence", "wayback", "retail"),
        missing_skill_examples=(
            "Wayback/backfill external evidence reconstruction",
            "BrightData source contract drift",
        ),
        notes="General source evidence is covered; external reconstruction deserves explicit skills.",
    ),
    ScriptSkillGroup(
        group_id="taxonomy_goldbook_specs",
        label="Taxonomy, Gold Book, specs, GTIN, and manufacturers",
        patterns=(
            "*gold*.py",
            "*spec*.py",
            "*gtin*.py",
            "*gs1*.py",
            "*manufacturer*.py",
            "*category*.py",
            "*taxonomy*.py",
        ),
        benchmark_domains=("gold-book", "data-fix", "helpdesk"),
        expected_skill_keywords=("spec", "category", "validator", "gtin"),
        missing_skill_examples=(
            "GTIN/GS1 provenance repair",
            "manufacturer alias normalization",
            "taxonomy reclassification impact check",
        ),
        notes="Gold Book is represented, but GTIN/manufacturer/taxonomy-specific workflows need more cases.",
    ),
    ScriptSkillGroup(
        group_id="survey_market_nfm_map",
        label="Survey, market sizing, NFM, MAP, and specialty surfaces",
        patterns=("*survey*.py", "*market*.py", "*nfm*.py", "*map*.py", "*abt*.py"),
        benchmark_domains=("hal-workflows", "data-pipelines"),
        expected_skill_keywords=("survey", "market", "map", "category count"),
        missing_skill_examples=(
            "survey question change route",
            "MAP violation reporting",
            "ABT outlier audit routing",
        ),
        notes="These look partially represented but not exhausted.",
    ),
)

BASIC_OPERATIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "cli_help",
        "CLI --help/introspection before execution",
        ("--help", "script --help"),
    ),
    ("dry_run", "dry-run/apply-false path before mutation", ("dry-run", "apply-false")),
    (
        "schema_validation",
        "input/output schema validation",
        ("schema validator", "fixture"),
    ),
    (
        "artifact_manifest",
        "artifact manifest and path receipts",
        ("artifact manifest", "manifest"),
    ),
    (
        "row_counts",
        "row counts, denominators, and before/after counts",
        ("row-count", "denominator", "count"),
    ),
    ("rollback", "rollback/reopen/undo plan before live apply", ("rollback", "reopen")),
    ("postcheck", "postcheck after apply or sync", ("postcheck", "after apply")),
    (
        "idempotency",
        "resume/idempotency and skip already-done rows",
        ("idempotent", "resume", "skip"),
    ),
    (
        "redaction",
        "redaction and secret-safe evidence handling",
        ("redaction", "secret"),
    ),
    (
        "screenshot_proof",
        "visual proof classification and screenshot review",
        ("screenshot", "visible proof"),
    ),
    (
        "owner_boundary",
        "owner, tenant, and purse boundary validation",
        ("owner", "tenant", "purse"),
    ),
    ("queue_wave", "queue/wave planning for batch work", ("queue", "wave")),
)


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _catalog_script_refs(root: Path) -> set[str]:
    catalog = _read_text(root / "docs" / "script_catalog.md")
    return {match.group(1) for match in SCRIPT_REF_RE.finditer(catalog)}


def _script_names(root: Path) -> list[str]:
    names = {
        path.name
        for path in (root / "scripts").glob("*.py")
        if path.is_file() and not path.name.startswith("__")
    }
    names.update(_catalog_script_refs(root))
    return sorted(names)


def _runbook_ids(root: Path) -> list[str]:
    ids: set[str] = set()
    for path in (root / "runbooks").glob("*.md"):
        match = RUNBOOK_ID_RE.match(path.name)
        if match:
            ids.add(match.group(1).upper())
    catalog = _read_text(root / "docs" / "runbook_catalog.md")
    for match in re.finditer(r"^- ([A-Z0-9]{2,5}):", catalog, flags=re.MULTILINE):
        ids.add(match.group(1).upper())
    return sorted(ids)


def _row_text(row: dict[str, Any]) -> str:
    parts = [
        str(row.get("skill_id") or ""),
        str(row.get("domain") or ""),
        str(row.get("label") or ""),
        " ".join(str(item) for item in row.get("tools") or []),
        " ".join(str(item) for item in row.get("runbooks") or []),
        " ".join(str(item) for item in row.get("examples") or []),
    ]
    return " ".join(parts).lower()


def _group_scripts(group: ScriptSkillGroup, scripts: list[str]) -> list[str]:
    return sorted(
        name
        for name in scripts
        if any(fnmatch.fnmatch(name, pattern) for pattern in group.patterns)
    )


def _matching_benchmark_rows(
    group: ScriptSkillGroup, benchmark_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in benchmark_rows:
        text = _row_text(row)
        if row.get("domain") in group.benchmark_domains or any(
            keyword.lower() in text for keyword in group.expected_skill_keywords
        ):
            rows.append(row)
    return rows


def _focus_matching_benchmark_rows(
    group: ScriptSkillGroup, benchmark_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in benchmark_rows:
        text = _row_text(row)
        if any(keyword.lower() in text for keyword in group.expected_skill_keywords):
            rows.append(row)
    return rows


def _operation_coverage(benchmark_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    corpus = "\n".join(_row_text(row) for row in benchmark_rows)
    rows: list[dict[str, Any]] = []
    for op_id, label, terms in BASIC_OPERATIONS:
        hits = [term for term in terms if term.lower() in corpus]
        rows.append(
            {
                "operation_id": op_id,
                "label": label,
                "covered": bool(hits),
                "hits": hits,
                "terms": list(terms),
            }
        )
    return rows


def _runbook_coverage(
    runbook_ids: list[str], benchmark_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    corpus = "\n".join(_row_text(row) for row in benchmark_rows)
    covered = [runbook for runbook in runbook_ids if runbook.lower() in corpus]
    missing = [runbook for runbook in runbook_ids if runbook not in covered]
    return {
        "runbook_count": len(runbook_ids),
        "covered_runbook_ids": covered,
        "missing_runbook_ids": missing,
        "coverage_rate": round(len(covered) / len(runbook_ids), 4)
        if runbook_ids
        else 0.0,
    }


def build_gap_report(
    *,
    mirror_root: Path = DEFAULT_MIRROR_ROOT,
    benchmark_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    benchmark_report = benchmark_report or build_report()
    benchmark_rows = list(benchmark_report["rows"])
    scripts = _script_names(mirror_root)
    runbooks = _runbook_ids(mirror_root)
    groups: list[dict[str, Any]] = []
    for group in SCRIPT_SKILL_GROUPS:
        script_matches = _group_scripts(group, scripts)
        broad_matches = _matching_benchmark_rows(group, benchmark_rows)
        row_matches = _focus_matching_benchmark_rows(group, benchmark_rows)
        specificity_ratio = (
            round(len(script_matches) / len(row_matches), 2) if row_matches else None
        )
        status = "covered"
        if script_matches and not row_matches:
            status = "missing_benchmark_domain"
        elif script_matches and len(row_matches) < 4:
            status = "thin"
        elif specificity_ratio is not None and specificity_ratio >= 4:
            status = "covered_but_too_coarse"
        groups.append(
            {
                **asdict(group),
                "script_count": len(script_matches),
                "script_examples": script_matches[:12],
                "benchmark_skill_count": len(row_matches),
                "benchmark_skill_examples": [
                    str(row["skill_id"]) for row in row_matches[:12]
                ],
                "broad_related_benchmark_skill_count": len(broad_matches),
                "broad_related_benchmark_skill_examples": [
                    str(row["skill_id"]) for row in broad_matches[:12]
                ],
                "script_to_skill_specificity_ratio": specificity_ratio,
                "coverage_status": status,
            }
        )
    grouped_scripts = {
        name for group in SCRIPT_SKILL_GROUPS for name in _group_scripts(group, scripts)
    }
    ungrouped = [name for name in scripts if name not in grouped_scripts]
    runbook_coverage = _runbook_coverage(runbooks, benchmark_rows)
    operation_rows = _operation_coverage(benchmark_rows)
    missing_operations = [
        row["operation_id"] for row in operation_rows if not row["covered"]
    ]
    high_gap_groups = [
        row["group_id"]
        for row in groups
        if row["coverage_status"]
        in {"missing_benchmark_domain", "thin", "covered_but_too_coarse"}
    ]
    return {
        "schema": "norman.control-plane-skill-gap-audit.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dry_run_only": True,
        "model_calls_executed": 0,
        "mirror_root": str(mirror_root),
        "script_count": len(scripts),
        "script_group_count": len(groups),
        "ungrouped_script_count": len(ungrouped),
        "ungrouped_script_examples": ungrouped[:40],
        "benchmark_skill_count": int(benchmark_report["skill_count"]),
        "runbook_coverage": runbook_coverage,
        "basic_operation_coverage": operation_rows,
        "missing_basic_operations": missing_operations,
        "high_gap_group_ids": high_gap_groups,
        "summary": {
            "covered_group_count": sum(
                1 for row in groups if row["coverage_status"] == "covered"
            ),
            "thin_or_coarse_group_count": sum(
                1
                for row in groups
                if row["coverage_status"] in {"thin", "covered_but_too_coarse"}
            ),
            "missing_group_count": sum(
                1
                for row in groups
                if row["coverage_status"] == "missing_benchmark_domain"
            ),
            "runbook_coverage_rate": runbook_coverage["coverage_rate"],
            "basic_operations_covered": sum(
                1 for row in operation_rows if row["covered"]
            ),
            "basic_operations_total": len(operation_rows),
            "verdict": (
                "not_exhausted"
                if high_gap_groups
                or runbook_coverage["missing_runbook_ids"]
                or missing_operations
                else "broadly_covered"
            ),
        },
        "groups": groups,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    runbook = report["runbook_coverage"]
    lines = [
        "# Control Plane Skill Gap Audit",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Dry-run only: {report['dry_run_only']}; model calls executed: {report['model_calls_executed']}",
        f"- Mirror root: `{report['mirror_root']}`",
        f"- Scripts indexed: {report['script_count']}; ungrouped examples: {report['ungrouped_script_count']}",
        f"- Benchmark skills compared: {report['benchmark_skill_count']}",
        f"- Verdict: `{summary['verdict']}`",
        f"- Runbook coverage: {len(runbook['covered_runbook_ids'])} / {runbook['runbook_count']} ({runbook['coverage_rate'] * 100:.1f}%)",
        f"- Basic operations covered: {summary['basic_operations_covered']} / {summary['basic_operations_total']}",
        "",
        "## Script Group Coverage",
        "",
        "| Group | Scripts | Direct benchmark skills | Broad related skills | Ratio | Status | Examples | Missing skill examples |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in report["groups"]:
        ratio = row["script_to_skill_specificity_ratio"]
        lines.append(
            "| {group} | {scripts} | {skills} | {broad} | {ratio} | {status} | {examples} | {missing} |".format(
                group=str(row["label"]).replace("|", "/"),
                scripts=row["script_count"],
                skills=row["benchmark_skill_count"],
                broad=row["broad_related_benchmark_skill_count"],
                ratio=f"{float(ratio):.2f}" if ratio is not None else "-",
                status=row["coverage_status"],
                examples=", ".join(row["script_examples"][:4]).replace("|", "/") or "-",
                missing=", ".join(row["missing_skill_examples"]).replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Runbook Coverage",
            "",
            f"- Missing runbook IDs: {', '.join(runbook['missing_runbook_ids']) or '-'}",
            "",
            "## Basic Operations",
            "",
            "| Operation | Covered | Hits |",
            "| --- | --- | --- |",
        ]
    )
    for row in report["basic_operation_coverage"]:
        lines.append(
            "| {label} | {covered} | {hits} |".format(
                label=str(row["label"]).replace("|", "/"),
                covered="yes" if row["covered"] else "no",
                hits=", ".join(row["hits"]) or "-",
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- The control-plane benchmark is broad but not exhausted. It covers the model-routing and authority pattern, but many script families still collapse dozens of real scripts into a small number of generalized skills.",
            "- Missing runbook IDs are not necessarily absent documentation; they mean the current benchmark does not yet name them explicitly as test rows.",
            "- The highest-value next cases are postcheck/idempotency/resume, exact-row mutation gates, customer deliverable/CMS, provider/QuickSight, source reconstruction, GTIN/manufacturer, survey/MAP/NFM, and per-runbook route cases for local drafts.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    output_md.write_text(render_markdown(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit mirrored control-plane scripts/runbooks against the work-domain benchmark."
    )
    parser.add_argument("--mirror-root", type=Path, default=DEFAULT_MIRROR_ROOT)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_gap_report(mirror_root=args.mirror_root)
    write_report(report, args.output_json, args.output_md)
    print(
        json.dumps(
            {
                "output_json": str(args.output_json),
                "output_md": str(args.output_md),
                "schema": report["schema"],
                "script_count": report["script_count"],
                "benchmark_skill_count": report["benchmark_skill_count"],
                "verdict": report["summary"]["verdict"],
                "high_gap_group_count": len(report["high_gap_group_ids"]),
                "runbook_coverage_rate": report["summary"]["runbook_coverage_rate"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
