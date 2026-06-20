#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_JSON = Path("/tmp/norman_tui_benchmarks/route_policy_drift_lint.json")
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_benchmarks/route_policy_drift_lint.md")


@dataclass(frozen=True)
class DriftRule:
    id: str
    severity: str
    pattern: re.Pattern[str]
    suggestion: str


@dataclass(frozen=True)
class DriftIssue:
    rule_id: str
    severity: str
    path: str
    line: int
    excerpt: str
    suggestion: str


DRIFT_RULES = (
    DriftRule(
        id="five_five_desired_default",
        severity="error",
        pattern=re.compile(
            r"\b(?:bedrock\s+)?(?:codex\s+)?5\.5\b.{0,100}\bdesired default\b",
            re.I,
        ),
        suggestion=(
            "Use GPT-5.4-first wording; reserve GPT-5.5 for final authority, "
            "tiebreaker, safety boundary, or failed evidence gates."
        ),
    ),
    DriftRule(
        id="five_five_default_route",
        severity="error",
        pattern=re.compile(
            r"(?:\bdesired\s+(?:route|target)\b.{0,100}\b5\.5\b.{0,40}\bdefault\b)"
            r"|(?:\b(?:bedrock\s+)?(?:codex\s+)?5\.5\b.{0,80}\bdefault\s+(?:route|for)\b)",
            re.I,
        ),
        suggestion=(
            "Do not describe GPT-5.5 as the default route unless the policy "
            "explicitly marks that lane as final-authority only."
        ),
    ),
    DriftRule(
        id="five_five_planner_verifier_flow",
        severity="error",
        pattern=re.compile(
            r"\b5\.5\s+(?:planner|planner/final)\b.*\b5\.5\s+verifier\b",
            re.I,
        ),
        suggestion=(
            "Replace 5.5-planner/verifier flows with local/cheap worker -> "
            "GPT-5.4 verifier -> GPT-5.5 final authority only when needed."
        ),
    ),
    DriftRule(
        id="five_five_verifier_owns_final",
        severity="error",
        pattern=re.compile(
            r"\b5\.5\s+verifier\b.{0,80}\b(?:owns|final acceptance)\b",
            re.I,
        ),
        suggestion=(
            "Make GPT-5.4 the normal verifier and GPT-5.5 the rare final "
            "authority/escalation lane."
        ),
    ),
)


DEFAULT_SCAN_GLOBS = (
    "scripts/tui_provider_readiness_benchmark.py",
    "scripts/tui_auto_mode_benchmark.py",
    "scripts/work_loop_canary.py",
    "tests/test_tui_provider_readiness_benchmark.py",
    "tests/test_tui_auto_mode_benchmark.py",
    "tests/test_work_loop_canary.py",
    "tmp/pro_agent_norman_harness_pack/reports/provider_readiness.md",
    "tmp/pro_agent_norman_harness_pack/reports/provider_readiness_prompts.json",
)


def _iter_existing_paths(root: Path, globs: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for item in globs:
        path = (root / item).resolve()
        if path.exists() and path.is_file():
            paths.append(path)
    return paths


def lint_file(path: Path, *, root: Path = REPO_ROOT) -> list[DriftIssue]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    rel = str(path.resolve().relative_to(root.resolve()))
    issues: list[DriftIssue] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        compact = line.strip()
        if not compact:
            continue
        for rule in DRIFT_RULES:
            if rule.pattern.search(compact):
                issues.append(
                    DriftIssue(
                        rule_id=rule.id,
                        severity=rule.severity,
                        path=rel,
                        line=line_number,
                        excerpt=compact[:240],
                        suggestion=rule.suggestion,
                    )
                )
                break
    return issues


def build_report(paths: Iterable[Path], *, root: Path = REPO_ROOT) -> dict[str, object]:
    scanned = list(paths)
    issues: list[DriftIssue] = []
    for path in scanned:
        issues.extend(lint_file(path, root=root))
    errors = [issue for issue in issues if issue.severity == "error"]
    return {
        "schema": "norman.route-policy-drift-lint.v1",
        "root": str(root),
        "scanned_files": [
            str(path.resolve().relative_to(root.resolve())) for path in scanned
        ],
        "issue_count": len(issues),
        "error_count": len(errors),
        "status": "fail" if errors else "pass",
        "issues": [asdict(issue) for issue in issues],
    }


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Route Policy Drift Lint",
        "",
        f"- Status: `{report['status']}`",
        f"- Files scanned: {len(report['scanned_files'])}",
        f"- Issues: {report['issue_count']}",
        f"- Errors: {report['error_count']}",
        "",
    ]
    issues = report.get("issues")
    if not isinstance(issues, list) or not issues:
        lines.append("No route-policy drift found.")
        return "\n".join(lines) + "\n"
    lines.extend(["| File | Line | Rule | Excerpt |", "| --- | ---: | --- | --- |"])
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        excerpt = str(issue.get("excerpt", "")).replace("|", "\\|")
        lines.append(
            f"| `{issue.get('path')}` | {issue.get('line')} | "
            f"`{issue.get('rule_id')}` | {excerpt} |"
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find stale 5.5-default route-policy language."
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--paths", nargs="*", default=list(DEFAULT_SCAN_GLOBS))
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--fail-on-error", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = _iter_existing_paths(args.root, args.paths)
    report = build_report(paths, root=args.root)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(report["summary"], indent=2)
        if "summary" in report
        else report["status"]
    )
    if args.fail_on_error and report["status"] == "fail":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
