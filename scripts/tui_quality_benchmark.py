#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = REPO_ROOT / "db" / "tui_quality_benchmark_cases.json"
DEFAULT_ANSWERS_EXAMPLE = REPO_ROOT / "db" / "tui_quality_shadow_answers.example.json"
DEFAULT_OUTPUT_JSON = Path("/tmp/norman_tui_quality_benchmark_report.json")
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_quality_benchmark_report.md")

SCORE_WEIGHTS = {
    "fact_recall": 0.30,
    "evidence_recall": 0.25,
    "trap_free": 0.20,
    "wisdom": 0.15,
    "context_efficiency": 0.10,
}


@dataclass
class RuleHit:
    id: str
    weight: float
    matched: bool
    missing: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class AnswerScore:
    label: str
    score: int
    fact_recall: float
    evidence_recall: float
    wisdom: float
    trap_free: float
    claim_precision_proxy: float
    hallucination_trap_hits: int
    context_efficiency: float
    estimated_answer_tokens: int
    estimated_context_tokens: int
    fact_hits: list[RuleHit]
    evidence_hits: list[RuleHit]
    wisdom_hits: list[RuleHit]
    trap_hits: list[RuleHit]
    notes: list[str] = field(default_factory=list)


@dataclass
class CaseReport:
    id: str
    title: str
    tui: str
    category: str
    prompt: str
    answer_scores: list[AnswerScore]
    best_answer: str = ""
    score_delta: int | None = None
    context_token_delta: int | None = None
    context_saved_pct: float | None = None


def _norm_text(value: Any) -> str:
    text = str(value or "").lower()
    return re.sub(r"\s+", " ", text).strip()


def _estimated_tokens(value: Any) -> int:
    text = str(value or "")
    if not text:
        return 0
    return max(1, round(len(text) / 4))


def _terms(rule: dict[str, Any], key: str) -> list[str]:
    values = rule.get(key)
    if isinstance(values, str):
        return [values]
    if isinstance(values, list):
        return [str(item) for item in values if str(item or "").strip()]
    return []


def _match_positive_rule(rule: dict[str, Any], answer: str) -> RuleHit:
    answer_norm = _norm_text(answer)
    all_terms = _terms(rule, "all_terms")
    any_terms = _terms(rule, "any_terms")
    missing: list[str] = []
    matched_terms: list[str] = []

    for term in all_terms:
        if _norm_text(term) in answer_norm:
            matched_terms.append(term)
        else:
            missing.append(term)

    any_matched = False
    for term in any_terms:
        if _norm_text(term) in answer_norm:
            matched_terms.append(term)
            any_matched = True

    if any_terms and not any_matched:
        missing.append("one of: " + ", ".join(any_terms))

    matched = not missing and bool(all_terms or any_terms)
    return RuleHit(
        id=str(rule.get("id") or ""),
        weight=float(rule.get("weight") or 1),
        matched=matched,
        missing=missing,
        matched_terms=matched_terms,
        description=str(rule.get("description") or rule.get("title") or ""),
    )


def _match_trap_rule(rule: dict[str, Any], answer: str) -> RuleHit:
    answer_norm = _norm_text(answer)
    forbidden_terms = _terms(rule, "forbidden_terms")
    all_terms = _terms(rule, "all_terms")
    matched_terms: list[str] = []

    for term in forbidden_terms:
        if _norm_text(term) in answer_norm:
            matched_terms.append(term)

    if all_terms and all(_norm_text(term) in answer_norm for term in all_terms):
        matched_terms.extend(all_terms)

    return RuleHit(
        id=str(rule.get("id") or ""),
        weight=float(rule.get("weight") or 1),
        matched=bool(matched_terms),
        matched_terms=matched_terms,
        description=str(rule.get("description") or rule.get("title") or ""),
    )


def _weighted_recall(hits: list[RuleHit]) -> float:
    total = sum(max(0.0, hit.weight) for hit in hits)
    if total <= 0:
        return 1.0
    matched = sum(max(0.0, hit.weight) for hit in hits if hit.matched)
    return round(matched / total, 4)


def _trap_free_score(traps: list[RuleHit]) -> float:
    total = sum(max(0.0, hit.weight) for hit in traps)
    if total <= 0:
        return 1.0
    hit_weight = sum(max(0.0, hit.weight) for hit in traps if hit.matched)
    return round(max(0.0, 1.0 - min(1.0, hit_weight / total)), 4)


def _context_efficiency_score(case: dict[str, Any], label: str) -> tuple[float, int]:
    tokens_by_label = case.get("context_tokens")
    if not isinstance(tokens_by_label, dict):
        return 1.0, 0
    baseline = int(tokens_by_label.get("baseline") or 0)
    current = int(tokens_by_label.get(label) or 0)
    if current <= 0:
        return 1.0, 0
    if baseline <= 0:
        return 1.0, current
    if label == "baseline":
        return 0.5, current
    saved_pct = max(0.0, (baseline - current) / baseline)
    return round(min(1.0, 0.5 + saved_pct), 4), current


def score_answer(case: dict[str, Any], label: str, answer: str) -> AnswerScore:
    fact_hits = [
        _match_positive_rule(rule, answer)
        for rule in case.get("required_facts", [])
        if isinstance(rule, dict)
    ]
    evidence_hits = [
        _match_positive_rule(rule, answer)
        for rule in case.get("required_evidence", [])
        if isinstance(rule, dict)
    ]
    wisdom_hits = [
        _match_positive_rule(rule, answer)
        for rule in case.get("wisdom_checks", [])
        if isinstance(rule, dict)
    ]
    trap_hits = [
        _match_trap_rule(rule, answer)
        for rule in case.get("known_traps", [])
        if isinstance(rule, dict)
    ]

    fact_recall = _weighted_recall(fact_hits)
    evidence_recall = _weighted_recall(evidence_hits)
    wisdom = _weighted_recall(wisdom_hits)
    trap_free = _trap_free_score(trap_hits)
    context_efficiency, context_tokens = _context_efficiency_score(case, label)

    positive_matched_weight = sum(
        hit.weight for hit in fact_hits + evidence_hits + wisdom_hits if hit.matched
    )
    trap_weight = sum(hit.weight for hit in trap_hits if hit.matched)
    claim_precision_proxy = (
        round(positive_matched_weight / (positive_matched_weight + trap_weight), 4)
        if positive_matched_weight + trap_weight > 0
        else 0.0
    )

    weighted_score = (
        SCORE_WEIGHTS["fact_recall"] * fact_recall
        + SCORE_WEIGHTS["evidence_recall"] * evidence_recall
        + SCORE_WEIGHTS["trap_free"] * trap_free
        + SCORE_WEIGHTS["wisdom"] * wisdom
        + SCORE_WEIGHTS["context_efficiency"] * context_efficiency
    )
    notes: list[str] = []
    if trap_free < 1.0:
        notes.append(
            "Known-trap language present; review for hallucination or overclaim."
        )
    if evidence_recall < 0.5:
        notes.append("Weak evidence coverage.")
    if fact_recall < 0.75:
        notes.append("Missing required facts.")
    if wisdom < 0.5:
        notes.append("Weak operator judgment coverage.")

    return AnswerScore(
        label=label,
        score=round(weighted_score * 100),
        fact_recall=fact_recall,
        evidence_recall=evidence_recall,
        wisdom=wisdom,
        trap_free=trap_free,
        claim_precision_proxy=claim_precision_proxy,
        hallucination_trap_hits=sum(1 for hit in trap_hits if hit.matched),
        context_efficiency=context_efficiency,
        estimated_answer_tokens=_estimated_tokens(answer),
        estimated_context_tokens=context_tokens,
        fact_hits=fact_hits,
        evidence_hits=evidence_hits,
        wisdom_hits=wisdom_hits,
        trap_hits=[hit for hit in trap_hits if hit.matched],
        notes=notes,
    )


def score_case(case: dict[str, Any]) -> CaseReport:
    answers = case.get("answers") if isinstance(case.get("answers"), dict) else {}
    answer_scores = [
        score_answer(case, label, str(answer or ""))
        for label, answer in sorted(answers.items())
        if str(answer or "").strip()
    ]
    answer_scores.sort(key=lambda item: item.label)

    best_answer = ""
    if answer_scores:
        best_answer = max(answer_scores, key=lambda item: item.score).label

    score_delta: int | None = None
    context_token_delta: int | None = None
    context_saved_pct: float | None = None
    by_label = {item.label: item for item in answer_scores}
    if "baseline" in by_label and "candidate" in by_label:
        score_delta = by_label["candidate"].score - by_label["baseline"].score
        base_tokens = by_label["baseline"].estimated_context_tokens
        candidate_tokens = by_label["candidate"].estimated_context_tokens
        if base_tokens and candidate_tokens:
            context_token_delta = candidate_tokens - base_tokens
            context_saved_pct = round(
                (base_tokens - candidate_tokens) / base_tokens * 100, 1
            )

    return CaseReport(
        id=str(case.get("id") or ""),
        title=str(case.get("title") or case.get("id") or ""),
        tui=str(case.get("tui") or ""),
        category=str(case.get("category") or ""),
        prompt=str(case.get("prompt") or ""),
        answer_scores=answer_scores,
        best_answer=best_answer,
        score_delta=score_delta,
        context_token_delta=context_token_delta,
        context_saved_pct=context_saved_pct,
    )


def load_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise ValueError(f"{path} does not contain a cases list")
    return [case for case in cases if isinstance(case, dict)]


def load_answer_overlay(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain an object")
    if not isinstance(data.get("answers"), list):
        raise ValueError(f"{path} does not contain an answers list")
    return data


def apply_answer_overlay(
    cases: list[dict[str, Any]], overlay: dict[str, Any]
) -> list[dict[str, Any]]:
    output = copy.deepcopy(cases)
    by_id = {str(case.get("id") or ""): case for case in output}
    replace = not bool(overlay.get("merge"))
    if replace:
        for case in output:
            case["answers"] = {}
            if "context_tokens" in case:
                case["context_tokens"] = {}

    for item in overlay.get("answers", []):
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("case_id") or "").strip()
        label = str(item.get("label") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if not case_id or not label or not answer:
            continue
        case = by_id.get(case_id)
        if not case:
            raise ValueError(f"answer overlay references unknown case_id: {case_id}")
        answers = case.setdefault("answers", {})
        if not isinstance(answers, dict):
            answers = {}
            case["answers"] = answers
        answers[label] = answer
        if item.get("context_tokens") is not None:
            context_tokens = case.setdefault("context_tokens", {})
            if not isinstance(context_tokens, dict):
                context_tokens = {}
                case["context_tokens"] = context_tokens
            context_tokens[label] = int(item.get("context_tokens") or 0)
    return output


def missing_answer_pairs(cases: list[dict[str, Any]]) -> list[str]:
    missing: list[str] = []
    for case in cases:
        answers = case.get("answers") if isinstance(case.get("answers"), dict) else {}
        labels = {
            str(label) for label in answers if str(answers.get(label) or "").strip()
        }
        if labels and {"baseline", "candidate"} - labels:
            missing.append(str(case.get("id") or ""))
    return missing


def build_report(
    cases: list[dict[str, Any]], *, run_metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    case_reports = [score_case(case) for case in cases]
    scored_answers = [
        answer for case_report in case_reports for answer in case_report.answer_scores
    ]
    candidate_scores = [
        answer.score
        for case_report in case_reports
        for answer in case_report.answer_scores
        if answer.label == "candidate"
    ]
    baseline_scores = [
        answer.score
        for case_report in case_reports
        for answer in case_report.answer_scores
        if answer.label == "baseline"
    ]
    deltas = [
        case_report.score_delta
        for case_report in case_reports
        if case_report.score_delta is not None
    ]
    saved_pcts = [
        case_report.context_saved_pct
        for case_report in case_reports
        if case_report.context_saved_pct is not None
    ]
    return {
        "schema": "norman.tui.quality-benchmark-report.v1",
        "generated_at": int(time.time()),
        "run": run_metadata or {},
        "score_weights": SCORE_WEIGHTS,
        "summary": {
            "case_count": len(case_reports),
            "answer_count": len(scored_answers),
            "candidate_avg_score": round(
                sum(candidate_scores) / len(candidate_scores), 1
            )
            if candidate_scores
            else None,
            "baseline_avg_score": round(sum(baseline_scores) / len(baseline_scores), 1)
            if baseline_scores
            else None,
            "candidate_vs_baseline_avg_delta": round(sum(deltas) / len(deltas), 1)
            if deltas
            else None,
            "avg_context_saved_pct": round(sum(saved_pcts) / len(saved_pcts), 1)
            if saved_pcts
            else None,
        },
        "cases": [asdict(case_report) for case_report in case_reports],
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    run = report.get("run") if isinstance(report.get("run"), dict) else {}
    lines = [
        "# TUI Quality Benchmark",
        "",
        "This report scores qualitative answer quality for TUI context changes. It is a deterministic evidence and trap check; final rollout decisions should still include human review of borderline cases.",
        "",
    ]
    if run:
        lines.extend(
            [
                "## Run",
                "",
                f"- Run ID: {run.get('run_id') or ''}",
                f"- Source: {run.get('source') or ''}",
                f"- Notes: {run.get('notes') or ''}",
                "",
            ]
        )
    lines.extend(
        [
            "## Summary",
            "",
            f"- Cases: {summary.get('case_count')}",
            f"- Answers scored: {summary.get('answer_count')}",
            f"- Candidate average score: {summary.get('candidate_avg_score')}",
            f"- Baseline average score: {summary.get('baseline_avg_score')}",
            f"- Candidate vs baseline average delta: {summary.get('candidate_vs_baseline_avg_delta')}",
            f"- Average context saved: {summary.get('avg_context_saved_pct')}%",
            "",
            "## Cases",
            "",
            "| Case | TUI | Category | Answer | Score | Fact | Evidence | Wisdom | Trap-free | Notes |",
            "|---|---|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for case in report.get("cases", []):
        for answer in case.get("answer_scores", []):
            notes = "; ".join(answer.get("notes") or [])
            lines.append(
                "| {case_id} | {tui} | {category} | {label} | {score} | {fact:.2f} | {evidence:.2f} | {wisdom:.2f} | {trap_free:.2f} | {notes} |".format(
                    case_id=case.get("id", ""),
                    tui=case.get("tui", ""),
                    category=case.get("category", ""),
                    label=answer.get("label", ""),
                    score=answer.get("score", 0),
                    fact=float(answer.get("fact_recall") or 0),
                    evidence=float(answer.get("evidence_recall") or 0),
                    wisdom=float(answer.get("wisdom") or 0),
                    trap_free=float(answer.get("trap_free") or 0),
                    notes=notes.replace("|", "/"),
                )
            )
    lines.append("")
    lines.append("## Review Flags")
    lines.append("")
    for case in report.get("cases", []):
        for answer in case.get("answer_scores", []):
            missing = [
                hit.get("id", "")
                for group in ("fact_hits", "evidence_hits", "wisdom_hits")
                for hit in answer.get(group, [])
                if not hit.get("matched")
            ]
            traps = [hit.get("id", "") for hit in answer.get("trap_hits", [])]
            if not missing and not traps:
                continue
            lines.append(f"- {case.get('id')} / {answer.get('label')}:")
            if missing:
                lines.append(f"  - Missing: {', '.join(missing)}")
            if traps:
                lines.append(f"  - Trap hits: {', '.join(traps)}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score qualitative TUI answer quality against real-world benchmark cases."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument(
        "--answers",
        type=Path,
        help=(
            "Optional shadow answer overlay. Use this for real baseline/candidate "
            "outputs without editing the case library."
        ),
    )
    parser.add_argument(
        "--require-pairs",
        action="store_true",
        help="Require every scored case to include both baseline and candidate answers.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--print-md", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = load_cases(args.cases)
    run_metadata: dict[str, Any] = {}
    if args.answers:
        overlay = load_answer_overlay(args.answers)
        cases = apply_answer_overlay(cases, overlay)
        run_metadata = {
            "run_id": str(overlay.get("run_id") or args.answers.stem),
            "source": str(args.answers),
            "notes": str(overlay.get("notes") or ""),
        }
    if args.require_pairs:
        missing = missing_answer_pairs(cases)
        if missing:
            raise ValueError(
                "missing baseline/candidate answer pairs for: " + ", ".join(missing)
            )
    report = build_report(cases, run_metadata=run_metadata)
    markdown = render_markdown(report)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    args.output_md.write_text(markdown, encoding="utf-8")
    if args.print_md:
        print(markdown)
    else:
        print(f"wrote {args.output_json}")
        print(f"wrote {args.output_md}")
        print(json.dumps(report.get("summary", {}), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
