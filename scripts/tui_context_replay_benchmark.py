#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTEXT_REPORT = Path("/tmp/norman_tui_context_shadow_benchmark.json")
DEFAULT_CASES = REPO_ROOT / "db" / "tui_quality_benchmark_cases.json"
DEFAULT_OUTPUT_JSON = Path("/tmp/norman_tui_context_replay_benchmark.json")
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_context_replay_benchmark.md")
DEFAULT_ANSWER_TEMPLATE = Path("/tmp/norman_tui_context_replay_answers.template.json")

MIN_ROW_SAVED_PCT = 50.0
MIN_ROW_SAVED_TOKENS = 4000


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _compact_int(value: Any) -> str:
    return f"{_coerce_int(value):,}"


def slugify(value: Any) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    aliases = {
        "control-plane": "control-plane",
        "control-plane-tui": "control-plane",
        "controlplane": "control-plane",
        "control-plane-bot": "control-plane",
        "control-plane-console": "control-plane",
        "control-plane-ui": "control-plane",
        "control-plane-agent": "control-plane",
        "control-plane-session": "control-plane",
        "control-plane-runbook": "control-plane",
        "control-plane-runbooks": "control-plane",
        "control-plane-confluence": "control-plane",
        "control-plane-cp": "control-plane",
        "cp": "control-plane",
        "leadership-kpis": "leadership-kpis",
        "leadership-kpi": "leadership-kpis",
        "kpis": "leadership-kpis",
        "kpi": "leadership-kpis",
        "tmi": "tmi-dashboards",
        "tmi-dashboards": "tmi-dashboards",
        "dashboard": "tmi-dashboards",
        "dashboards": "tmi-dashboards",
        "market": "market-sizing",
        "market-sizing": "market-sizing",
        "market-size": "market-sizing",
        "goldbook": "gold-book",
        "gold-book": "gold-book",
        "platinum": "platinum-standard",
        "platinum-standard": "platinum-standard",
        "panel": "panelbot",
        "panelbot": "panelbot",
        "panel-bot": "panelbot",
        "mls": "mls",
        "infra": "infra",
        "infrastructure": "infra",
        "compere": "compere",
        "keystone": "compere",
        "earlybird": "earlybird",
        "early-bird": "earlybird",
        "scout": "scout",
        "norman": "__aggregate__",
        "aggregate": "__aggregate__",
        "operator": "__aggregate__",
    }
    return aliases.get(clean, clean)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_context_report(path: Path) -> dict[str, Any]:
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a context report object")
    if not isinstance(data.get("rows"), list):
        raise ValueError(f"{path} does not contain rows")
    return data


def load_cases(path: Path) -> list[dict[str, Any]]:
    data = _load_json(path)
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise ValueError(f"{path} does not contain a cases list")
    return [case for case in cases if isinstance(case, dict)]


def _source_tokens(row: dict[str, Any], source_key: str, label: str) -> int:
    sources = row.get(source_key)
    if not isinstance(sources, list):
        return 0
    total = 0
    for item in sources:
        if isinstance(item, dict) and str(item.get("label") or "") == label:
            total += _coerce_int(item.get("tokens"))
    return total


def _source_details(row: dict[str, Any], source_key: str) -> list[str]:
    sources = row.get(source_key)
    if not isinstance(sources, list):
        return []
    details: list[str] = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        tokens = _coerce_int(item.get("tokens"))
        detail = str(item.get("detail") or "").strip()
        mode = str(item.get("mode") or "").strip()
        parts = [label]
        if mode:
            parts.append(mode)
        parts.append(f"{tokens:,} tok")
        if detail:
            parts.append(detail)
        details.append(" - ".join(parts))
    return details


def _row_verdict(row: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not row.get("reachable", True):
        reasons.append("unreachable")
    if not row.get("state_db_enabled"):
        reasons.append("state DB disabled")
    if _coerce_float(row.get("saved_pct")) < MIN_ROW_SAVED_PCT:
        reasons.append("low savings pct")
    if _coerce_int(row.get("saved_tokens")) < MIN_ROW_SAVED_TOKENS:
        reasons.append("low saved tokens")
    if row.get("live_prompt_behavior_changed"):
        reasons.append("live behavior already changed")
    if (
        row.get("needs_retrieval_for_older_details")
        and _source_tokens(row, "packed_sources", "evidence refs") <= 0
    ):
        reasons.append("missing evidence refs")
    if reasons:
        return "review", reasons
    if row.get("requires_shadow_run_before_activation"):
        return "shadow-ready", ["needs real shadow answer before activation"]
    return "pass", []


def build_row_proofs(report: dict[str, Any]) -> list[dict[str, Any]]:
    proofs: list[dict[str, Any]] = []
    for row in report.get("rows", []):
        if not isinstance(row, dict):
            continue
        verdict, reasons = _row_verdict(row)
        older_replaced = _source_tokens(row, "excluded_sources", "older turn bodies")
        evidence_refs = _source_tokens(row, "packed_sources", "evidence refs")
        raw_tail_replaced = _source_tokens(
            row, "excluded_sources", "raw pane/log tails"
        )
        tail_digest = _source_tokens(row, "packed_sources", "tail digest")
        older_ref_saved_pct = (
            round((older_replaced - evidence_refs) / older_replaced * 100, 1)
            if older_replaced > 0
            else None
        )
        tail_saved_pct = (
            round((raw_tail_replaced - tail_digest) / raw_tail_replaced * 100, 1)
            if raw_tail_replaced > 0
            else None
        )
        proofs.append(
            {
                "slug": str(row.get("slug") or ""),
                "reachable": bool(row.get("reachable", True)),
                "state": str(row.get("state") or ""),
                "current_tokens": _coerce_int(row.get("current_tokens")),
                "packed_tokens": _coerce_int(row.get("packed_tokens")),
                "saved_tokens": _coerce_int(row.get("saved_tokens")),
                "saved_pct": _coerce_float(row.get("saved_pct")),
                "saved_cost_label": str(row.get("saved_cost_label") or ""),
                "state_db_enabled": bool(row.get("state_db_enabled")),
                "history_format": str(row.get("history_format") or ""),
                "quality_gate": {
                    "needs_retrieval_for_older_details": bool(
                        row.get("needs_retrieval_for_older_details")
                    ),
                    "requires_shadow_run_before_activation": bool(
                        row.get("requires_shadow_run_before_activation")
                    ),
                    "live_prompt_behavior_changed": bool(
                        row.get("live_prompt_behavior_changed")
                    ),
                },
                "older_turn_reference_proof": {
                    "older_body_tokens_replaced": older_replaced,
                    "evidence_ref_tokens": evidence_refs,
                    "saved_pct": older_ref_saved_pct,
                },
                "tail_digest_proof": {
                    "raw_tail_tokens_replaced": raw_tail_replaced,
                    "tail_digest_tokens": tail_digest,
                    "saved_pct": tail_saved_pct,
                },
                "included_sources": _source_details(row, "packed_sources"),
                "replaced_sources": _source_details(row, "excluded_sources"),
                "verdict": verdict,
                "reasons": reasons,
            }
        )
    return proofs


def _case_context_tokens(
    case: dict[str, Any],
    row_by_slug: dict[str, dict[str, Any]],
    summary: dict[str, Any],
) -> tuple[str, int, int, bool]:
    slug = slugify(case.get("tui"))
    if slug == "__aggregate__":
        return (
            slug,
            _coerce_int(summary.get("total_current_tokens")),
            _coerce_int(summary.get("total_packed_tokens")),
            True,
        )
    row = row_by_slug.get(slug)
    if row:
        return (
            slug,
            _coerce_int(row.get("current_tokens")),
            _coerce_int(row.get("packed_tokens")),
            True,
        )
    context_tokens = (
        case.get("context_tokens")
        if isinstance(case.get("context_tokens"), dict)
        else {}
    )
    return (
        slug,
        _coerce_int(context_tokens.get("baseline")),
        _coerce_int(context_tokens.get("candidate")),
        False,
    )


def build_case_replays(
    cases: list[dict[str, Any]],
    row_proofs: list[dict[str, Any]],
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    row_by_slug = {str(row.get("slug") or ""): row for row in row_proofs}
    replays: list[dict[str, Any]] = []
    for case in cases:
        matched_slug, baseline_tokens, candidate_tokens, has_context_row = (
            _case_context_tokens(case, row_by_slug, summary)
        )
        saved_tokens = max(0, baseline_tokens - candidate_tokens)
        saved_pct = (
            round(saved_tokens / baseline_tokens * 100, 1)
            if baseline_tokens > 0
            else 0.0
        )
        answers = case.get("answers") if isinstance(case.get("answers"), dict) else {}
        evidence_rules = [
            str(rule.get("id") or "")
            for rule in case.get("required_evidence", [])
            if isinstance(rule, dict)
        ]
        fact_rules = [
            str(rule.get("id") or "")
            for rule in case.get("required_facts", [])
            if isinstance(rule, dict)
        ]
        wisdom_rules = [
            str(rule.get("id") or "")
            for rule in case.get("wisdom_checks", [])
            if isinstance(rule, dict)
        ]
        replays.append(
            {
                "case_id": str(case.get("id") or ""),
                "title": str(case.get("title") or case.get("id") or ""),
                "tui": str(case.get("tui") or ""),
                "matched_context_slug": matched_slug,
                "has_context_row": has_context_row,
                "baseline_tokens": baseline_tokens,
                "candidate_tokens": candidate_tokens,
                "saved_tokens": saved_tokens,
                "saved_pct": saved_pct,
                "has_seed_baseline_answer": bool(
                    str(answers.get("baseline") or "").strip()
                ),
                "has_seed_candidate_answer": bool(
                    str(answers.get("candidate") or "").strip()
                ),
                "required_fact_rules": fact_rules,
                "required_evidence_rules": evidence_rules,
                "wisdom_rules": wisdom_rules,
                "needs_shadow_pair": not (
                    str(answers.get("baseline") or "").strip()
                    and str(answers.get("candidate") or "").strip()
                ),
            }
        )
    return replays


def build_report(
    context_report: dict[str, Any], cases: list[dict[str, Any]]
) -> dict[str, Any]:
    context_summary = (
        context_report.get("summary")
        if isinstance(context_report.get("summary"), dict)
        else {}
    )
    row_proofs = build_row_proofs(context_report)
    case_replays = build_case_replays(cases, row_proofs, context_summary)
    reachable_rows = [row for row in row_proofs if row.get("reachable")]
    older_rows = [
        row
        for row in reachable_rows
        if _coerce_int(
            row.get("older_turn_reference_proof", {}).get("older_body_tokens_replaced")
        )
        > 0
    ]
    shadow_ready_rows = [
        row for row in reachable_rows if row.get("verdict") == "shadow-ready"
    ]
    review_rows = [row for row in reachable_rows if row.get("verdict") == "review"]
    case_rows_with_context = [
        case for case in case_replays if case.get("has_context_row")
    ]
    case_rows_needing_shadow = [
        case for case in case_replays if case.get("needs_shadow_pair")
    ]
    shadow_run_ready = bool(reachable_rows) and not review_rows
    activation_safe = (
        shadow_run_ready
        and not shadow_ready_rows
        and not case_rows_needing_shadow
        and all(
            not (
                row.get("quality_gate", {}).get("requires_shadow_run_before_activation")
            )
            for row in reachable_rows
        )
    )
    return {
        "schema": "norman.tui.context-replay-benchmark.v1",
        "generated_at": int(time.time()),
        "source_context_schema": str(context_report.get("schema") or ""),
        "summary": {
            "row_count": len(row_proofs),
            "reachable_rows": len(reachable_rows),
            "total_current_tokens": _coerce_int(
                context_summary.get("total_current_tokens")
            ),
            "total_packed_tokens": _coerce_int(
                context_summary.get("total_packed_tokens")
            ),
            "total_saved_tokens": _coerce_int(
                context_summary.get("total_saved_tokens")
            ),
            "total_saved_pct": _coerce_float(context_summary.get("saved_pct")),
            "db_enabled_rows": sum(
                1 for row in reachable_rows if row.get("state_db_enabled")
            ),
            "rows_with_older_reference_proof": len(older_rows),
            "shadow_ready_rows": len(shadow_ready_rows),
            "review_rows": len(review_rows),
            "case_count": len(case_replays),
            "cases_with_context_rows": len(case_rows_with_context),
            "cases_needing_shadow_pairs": len(case_rows_needing_shadow),
            "shadow_run_ready": shadow_run_ready,
            "activation_safe": activation_safe,
        },
        "row_proofs": row_proofs,
        "case_replays": case_replays,
    }


def build_answer_template(report: dict[str, Any]) -> dict[str, Any]:
    answers: list[dict[str, Any]] = []
    for case in report.get("case_replays", []):
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("case_id") or "")
        if not case_id:
            continue
        answers.append(
            {
                "case_id": case_id,
                "label": "baseline",
                "context_tokens": _coerce_int(case.get("baseline_tokens")),
                "answer": "",
            }
        )
        answers.append(
            {
                "case_id": case_id,
                "label": "candidate",
                "context_tokens": _coerce_int(case.get("candidate_tokens")),
                "answer": "",
            }
        )
    return {
        "schema": "norman.tui.quality-shadow-answers.v1",
        "run_id": f"context-replay-{int(time.time())}",
        "notes": (
            "Fill baseline/candidate with real model outputs. Baseline should use the "
            "full current context. Candidate should use the compact DB/reference packet."
        ),
        "answers": answers,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# TUI Context Replay Benchmark",
        "",
        "Read-only proof packet for database-backed TUI context. This report combines real context-pack rows with benchmark cases, so we can see cost reduction, evidence-pointer coverage, and the remaining shadow-answer gate before changing live prompt behavior.",
        "",
        "## Summary",
        "",
        f"- Rows: {summary.get('reachable_rows')}/{summary.get('row_count')} reachable",
        f"- Tokens: {_compact_int(summary.get('total_current_tokens'))} -> {_compact_int(summary.get('total_packed_tokens'))}",
        f"- Saved: {_compact_int(summary.get('total_saved_tokens'))} tokens ({summary.get('total_saved_pct')}%)",
        f"- DB-enabled rows: {summary.get('db_enabled_rows')}",
        f"- Rows with older-turn reference proof: {summary.get('rows_with_older_reference_proof')}",
        f"- Shadow-ready rows: {summary.get('shadow_ready_rows')}",
        f"- Review rows: {summary.get('review_rows')}",
        f"- Benchmark cases with context rows: {summary.get('cases_with_context_rows')}/{summary.get('case_count')}",
        f"- Cases still needing real shadow pairs: {summary.get('cases_needing_shadow_pairs')}",
        f"- Safe to run shadow now: {'yes' if summary.get('shadow_run_ready') else 'no'}",
        f"- Activation safe now: {'yes' if summary.get('activation_safe') else 'no'}",
        "",
        "## Row Proofs",
        "",
        "| TUI | Current | Packed | Saved | Cost saved | Older bodies -> refs | Raw tails -> digest | Verdict |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("row_proofs", []):
        older = row.get("older_turn_reference_proof") or {}
        tail = row.get("tail_digest_proof") or {}
        older_label = (
            f"{_compact_int(older.get('older_body_tokens_replaced'))} -> {_compact_int(older.get('evidence_ref_tokens'))}"
            if _coerce_int(older.get("older_body_tokens_replaced")) > 0
            else ""
        )
        tail_label = (
            f"{_compact_int(tail.get('raw_tail_tokens_replaced'))} -> {_compact_int(tail.get('tail_digest_tokens'))}"
            if _coerce_int(tail.get("raw_tail_tokens_replaced")) > 0
            else ""
        )
        verdict = str(row.get("verdict") or "")
        reasons = row.get("reasons") if isinstance(row.get("reasons"), list) else []
        if reasons:
            verdict = f"{verdict}: {', '.join(str(item) for item in reasons)}"
        lines.append(
            "| {slug} | {current} | {packed} | {saved} ({pct}%) | {cost} | {older} | {tail} | {verdict} |".format(
                slug=row.get("slug", ""),
                current=_compact_int(row.get("current_tokens")),
                packed=_compact_int(row.get("packed_tokens")),
                saved=_compact_int(row.get("saved_tokens")),
                pct=row.get("saved_pct", 0),
                cost=row.get("saved_cost_label") or "",
                older=older_label,
                tail=tail_label,
                verdict=verdict,
            )
        )
    lines.extend(
        [
            "",
            "## Case Replay Map",
            "",
            "| Case | TUI | Context row | Baseline | Candidate | Saved | Needs shadow pair |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for case in report.get("case_replays", []):
        lines.append(
            "| {case_id} | {tui} | {slug} | {baseline} | {candidate} | {saved} ({pct}%) | {shadow} |".format(
                case_id=case.get("case_id", ""),
                tui=case.get("tui", ""),
                slug=case.get("matched_context_slug", ""),
                baseline=_compact_int(case.get("baseline_tokens")),
                candidate=_compact_int(case.get("candidate_tokens")),
                saved=_compact_int(case.get("saved_tokens")),
                pct=case.get("saved_pct", 0),
                shadow="yes" if case.get("needs_shadow_pair") else "no",
            )
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a replay/evidence proof packet for DB-backed TUI context."
    )
    parser.add_argument("--context-report", type=Path, default=DEFAULT_CONTEXT_REPORT)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument(
        "--output-answer-template",
        type=Path,
        default=DEFAULT_ANSWER_TEMPLATE,
        help="Write a baseline/candidate answer overlay template for the quality scorer.",
    )
    parser.add_argument("--print-md", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    context_report = load_context_report(args.context_report)
    cases = load_cases(args.cases)
    report = build_report(context_report, cases)
    markdown = render_markdown(report)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    args.output_md.write_text(markdown, encoding="utf-8")
    if args.output_answer_template:
        args.output_answer_template.write_text(
            json.dumps(build_answer_template(report), indent=2, sort_keys=True),
            encoding="utf-8",
        )
    if args.print_md:
        print(markdown)
    else:
        print(f"wrote {args.output_json}")
        print(f"wrote {args.output_md}")
        if args.output_answer_template:
            print(f"wrote {args.output_answer_template}")
        print(json.dumps(report.get("summary", {}), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
