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
    "fact_recall": 0.25,
    "evidence_recall": 0.20,
    "trap_free": 0.20,
    "wisdom": 0.15,
    "completeness": 0.10,
    "reasoning_depth": 0.05,
    "context_efficiency": 0.05,
}

CONTRACT_NEXT_STEP_MARKERS = (
    "next",
    "probe",
    "validate",
    "validation",
    "test",
    "follow-up",
    "follow up",
    "measure",
)
CONTRACT_CAVEAT_MARKERS = (
    "caveat",
    "not enough",
    "not invoice-grade",
    "not invoice grade",
    "not safe",
    "hold",
    "blocked",
    "until",
    "before",
    "do not",
)
CONTRACT_UNCERTAINTY_MARKERS = (
    "uncertain",
    "uncertainty",
    "confidence",
    "unclear",
    "ambiguous",
    "unknown",
    "not enough evidence",
)
CONTRACT_COMPARISON_MARKERS = (
    "option",
    "versus",
    "vs",
    "instead",
    "tradeoff",
    "trade-off",
    "compare",
    "cost",
    "risk",
    "authority",
)
CONTRACT_OBSERVED_EXPECTED_MARKERS = (
    "observed",
    "expected",
    "baseline",
    "conflict",
    "contradict",
)
CONTRACT_REASONING_MARKERS = (
    "because",
    "therefore",
    "however",
    "if",
    "then",
    "hypothesis",
    "evidence",
    "decision",
    "tradeoff",
    "trade-off",
    "risk",
    "cost",
    "uncertainty",
    "confidence",
    "next",
    "validate",
)


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
    contract_applied: bool
    fact_recall: float
    evidence_recall: float
    wisdom: float
    trap_free: float
    completeness: float
    reasoning_depth: float
    contract_score: float
    claim_precision_proxy: float
    hallucination_trap_hits: int
    context_efficiency: float
    estimated_answer_tokens: int
    estimated_context_tokens: int
    fact_hits: list[RuleHit]
    evidence_hits: list[RuleHit]
    wisdom_hits: list[RuleHit]
    contract_hits: list[RuleHit]
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
    candidate_regressions: list[str] = field(default_factory=list)
    candidate_dominates_baseline: bool | None = None


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


def _split_sentences(answer: str) -> list[str]:
    return [
        fragment.strip()
        for fragment in re.split(r"(?:[.!?]+[\s\n]+)|\n+", str(answer or ""))
        if fragment.strip()
    ]


def _contains_any(answer_norm: str, markers: tuple[str, ...]) -> list[str]:
    return [marker for marker in markers if marker in answer_norm]


def _section_present(answer: str, section: str) -> bool:
    if not str(section or "").strip():
        return False
    answer_lower = str(answer or "").lower()
    section_lower = str(section).strip().lower()
    if re.search(
        rf"(^|[\r\n])\s*{re.escape(section_lower)}\s*[:\-]",
        answer_lower,
        flags=re.MULTILINE,
    ):
        return True
    return section_lower in _norm_text(answer)


def _rule_hit(
    *,
    rule_id: str,
    description: str,
    matched: bool,
    missing: list[str] | None = None,
    matched_terms: list[str] | None = None,
    weight: float = 1.0,
) -> RuleHit:
    return RuleHit(
        id=rule_id,
        weight=weight,
        matched=matched,
        missing=missing or [],
        matched_terms=matched_terms or [],
        description=description,
    )


def _score_answer_contract(
    answer: str, contract: dict[str, Any]
) -> tuple[float, float, float, list[RuleHit]]:
    answer_norm = _norm_text(answer)
    words = [word for word in str(answer or "").split() if word.strip()]
    sentences = _split_sentences(answer)
    completeness_hits: list[RuleHit] = []
    reasoning_hits: list[RuleHit] = []

    min_words = int(contract.get("min_response_words") or 0)
    if min_words > 0:
        completeness_hits.append(
            _rule_hit(
                rule_id="contract-min-response-words",
                description=f"at least {min_words} response words",
                matched=len(words) >= min_words,
                missing=[] if len(words) >= min_words else [str(min_words)],
            )
        )

    min_sentences = int(contract.get("min_sentences") or 0)
    if min_sentences > 0:
        completeness_hits.append(
            _rule_hit(
                rule_id="contract-min-sentences",
                description=f"at least {min_sentences} sentences",
                matched=len(sentences) >= min_sentences,
                missing=[] if len(sentences) >= min_sentences else [str(min_sentences)],
            )
        )

    required_sections = _terms(contract, "required_sections")
    if required_sections:
        missing_sections = [
            section
            for section in required_sections
            if not _section_present(answer, section)
        ]
        completeness_hits.append(
            _rule_hit(
                rule_id="contract-required-sections",
                description="required sections present",
                matched=not missing_sections,
                missing=missing_sections,
                matched_terms=[
                    section
                    for section in required_sections
                    if section not in missing_sections
                ],
            )
        )

    required_terms = _terms(contract, "required_terms")
    if required_terms:
        missing_terms = [
            term for term in required_terms if _norm_text(term) not in answer_norm
        ]
        completeness_hits.append(
            _rule_hit(
                rule_id="contract-required-terms",
                description="required contract terms present",
                matched=not missing_terms,
                missing=missing_terms,
                matched_terms=[
                    term for term in required_terms if term not in missing_terms
                ],
            )
        )

    forbidden_terms = _terms(contract, "forbidden_terms")
    if forbidden_terms:
        forbidden_hits = [
            term for term in forbidden_terms if _norm_text(term) in answer_norm
        ]
        completeness_hits.append(
            _rule_hit(
                rule_id="contract-forbidden-terms",
                description="forbidden contract terms absent",
                matched=not forbidden_hits,
                missing=forbidden_hits,
                matched_terms=forbidden_hits,
            )
        )

    if contract.get("requires_next_step"):
        next_terms = _contains_any(answer_norm, CONTRACT_NEXT_STEP_MARKERS)
        completeness_hits.append(
            _rule_hit(
                rule_id="contract-next-step",
                description="explicit next step or validation probe",
                matched=bool(next_terms),
                missing=[] if next_terms else ["next step"],
                matched_terms=next_terms,
            )
        )

    if contract.get("requires_caveat"):
        caveat_terms = _contains_any(answer_norm, CONTRACT_CAVEAT_MARKERS)
        completeness_hits.append(
            _rule_hit(
                rule_id="contract-caveat",
                description="explicit caveat, hold, or safety guard",
                matched=bool(caveat_terms),
                missing=[] if caveat_terms else ["caveat"],
                matched_terms=caveat_terms,
            )
        )

    if contract.get("requires_uncertainty"):
        uncertainty_terms = _contains_any(answer_norm, CONTRACT_UNCERTAINTY_MARKERS)
        reasoning_hits.append(
            _rule_hit(
                rule_id="contract-uncertainty",
                description="states uncertainty or confidence",
                matched=bool(uncertainty_terms),
                missing=[] if uncertainty_terms else ["uncertainty"],
                matched_terms=uncertainty_terms,
            )
        )

    if contract.get("requires_comparison"):
        comparison_terms = _contains_any(answer_norm, CONTRACT_COMPARISON_MARKERS)
        reasoning_hits.append(
            _rule_hit(
                rule_id="contract-comparison",
                description="compares at least two options or tradeoffs",
                matched=len(comparison_terms) >= 2,
                missing=[] if len(comparison_terms) >= 2 else ["comparison"],
                matched_terms=comparison_terms,
            )
        )

    if contract.get("requires_observed_vs_expected"):
        observed_terms = _contains_any(answer_norm, CONTRACT_OBSERVED_EXPECTED_MARKERS)
        reasoning_hits.append(
            _rule_hit(
                rule_id="contract-observed-vs-expected",
                description="contrasts observed signals with baseline or expected state",
                matched=len(observed_terms) >= 2,
                missing=[] if len(observed_terms) >= 2 else ["observed vs expected"],
                matched_terms=observed_terms,
            )
        )

    min_reasoning_markers = int(contract.get("min_reasoning_markers") or 0)
    if min_reasoning_markers > 0:
        reasoning_terms = _contains_any(answer_norm, CONTRACT_REASONING_MARKERS)
        reasoning_hits.append(
            _rule_hit(
                rule_id="contract-reasoning-markers",
                description=f"at least {min_reasoning_markers} reasoning markers",
                matched=len(reasoning_terms) >= min_reasoning_markers,
                missing=(
                    []
                    if len(reasoning_terms) >= min_reasoning_markers
                    else [str(min_reasoning_markers)]
                ),
                matched_terms=reasoning_terms,
            )
        )

    completeness = _weighted_recall(completeness_hits)
    reasoning_depth = _weighted_recall(reasoning_hits)
    contract_hits = [*completeness_hits, *reasoning_hits]
    contract_score = _weighted_recall(contract_hits)
    return completeness, reasoning_depth, contract_score, contract_hits


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
    answer_contract = case.get("answer_contract")
    contract_applied = isinstance(answer_contract, dict)
    completeness = 1.0
    reasoning_depth = 1.0
    contract_score = 1.0
    contract_hits: list[RuleHit] = []
    if contract_applied:
        completeness, reasoning_depth, contract_score, contract_hits = (
            _score_answer_contract(answer, answer_contract)
        )

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
        + SCORE_WEIGHTS["completeness"] * completeness
        + SCORE_WEIGHTS["reasoning_depth"] * reasoning_depth
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
    if completeness < 1.0:
        notes.append("Incomplete answer contract coverage.")
    if reasoning_depth < 1.0:
        notes.append("Shallow reasoning structure for this case.")

    return AnswerScore(
        label=label,
        score=round(weighted_score * 100),
        contract_applied=contract_applied,
        fact_recall=fact_recall,
        evidence_recall=evidence_recall,
        wisdom=wisdom,
        trap_free=trap_free,
        completeness=completeness,
        reasoning_depth=reasoning_depth,
        contract_score=contract_score,
        claim_precision_proxy=claim_precision_proxy,
        hallucination_trap_hits=sum(1 for hit in trap_hits if hit.matched),
        context_efficiency=context_efficiency,
        estimated_answer_tokens=_estimated_tokens(answer),
        estimated_context_tokens=context_tokens,
        fact_hits=fact_hits,
        evidence_hits=evidence_hits,
        wisdom_hits=wisdom_hits,
        contract_hits=[hit for hit in contract_hits if not hit.matched],
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
    candidate_regressions: list[str] = []
    candidate_dominates_baseline: bool | None = None
    by_label = {item.label: item for item in answer_scores}
    if "baseline" in by_label and "candidate" in by_label:
        baseline = by_label["baseline"]
        candidate = by_label["candidate"]
        score_delta = candidate.score - baseline.score
        base_tokens = by_label["baseline"].estimated_context_tokens
        candidate_tokens = by_label["candidate"].estimated_context_tokens
        if base_tokens and candidate_tokens:
            context_token_delta = candidate_tokens - base_tokens
            context_saved_pct = round(
                (base_tokens - candidate_tokens) / base_tokens * 100, 1
            )
        comparisons = {
            "score": (candidate.score, baseline.score),
            "fact_recall": (candidate.fact_recall, baseline.fact_recall),
            "evidence_recall": (candidate.evidence_recall, baseline.evidence_recall),
            "wisdom": (candidate.wisdom, baseline.wisdom),
            "trap_free": (candidate.trap_free, baseline.trap_free),
            "completeness": (candidate.completeness, baseline.completeness),
            "reasoning_depth": (
                candidate.reasoning_depth,
                baseline.reasoning_depth,
            ),
            "claim_precision_proxy": (
                candidate.claim_precision_proxy,
                baseline.claim_precision_proxy,
            ),
        }
        candidate_regressions = [
            name
            for name, (cand_value, base_value) in comparisons.items()
            if cand_value < base_value
        ]
        candidate_dominates_baseline = not candidate_regressions

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
        candidate_regressions=candidate_regressions,
        candidate_dominates_baseline=candidate_dominates_baseline,
    )


def load_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise ValueError(f"{path} does not contain a cases list")
    output = [case for case in cases if isinstance(case, dict)]
    validate_cases(output)
    return output


def load_answer_overlay(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain an object")
    if not isinstance(data.get("answers"), list):
        raise ValueError(f"{path} does not contain an answers list")
    validate_answer_overlay(data)
    return data


def _validate_rule_group(
    case_id: str,
    key: str,
    rules: Any,
    errors: list[str],
) -> None:
    if rules is None:
        return
    if not isinstance(rules, list):
        errors.append(f"{case_id}: {key} must be a list")
        return
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"{case_id}: {key}[{index}] must be an object")
            continue
        if not str(rule.get("id") or "").strip():
            errors.append(f"{case_id}: {key}[{index}] is missing id")
        if not (
            _terms(rule, "all_terms")
            or _terms(rule, "any_terms")
            or _terms(rule, "forbidden_terms")
        ):
            errors.append(f"{case_id}: {key}[{index}] must name at least one term")
        weight = rule.get("weight")
        if weight is not None:
            try:
                if float(weight) < 0:
                    raise ValueError("negative")
            except (TypeError, ValueError):
                errors.append(f"{case_id}: {key}[{index}] has invalid weight")


def _validate_answer_contract(case_id: str, contract: Any, errors: list[str]) -> None:
    if contract is None:
        return
    if not isinstance(contract, dict):
        errors.append(f"{case_id}: answer_contract must be an object")
        return
    for key in ("min_response_words", "min_sentences", "min_reasoning_markers"):
        if contract.get(key) is None:
            continue
        try:
            if int(contract.get(key) or 0) < 0:
                raise ValueError("negative")
        except (TypeError, ValueError):
            errors.append(
                f"{case_id}: answer_contract.{key} must be a non-negative int"
            )
    for key in (
        "required_sections",
        "required_terms",
        "forbidden_terms",
    ):
        values = contract.get(key)
        if values is None:
            continue
        if not isinstance(values, (list, str)):
            errors.append(f"{case_id}: answer_contract.{key} must be a list or string")
    for key in (
        "requires_next_step",
        "requires_caveat",
        "requires_uncertainty",
        "requires_comparison",
        "requires_observed_vs_expected",
    ):
        if key in contract and not isinstance(contract.get(key), bool):
            errors.append(f"{case_id}: answer_contract.{key} must be a boolean")


def validate_cases(cases: list[dict[str, Any]]) -> None:
    errors: list[str] = []
    seen_ids: set[str] = set()
    for index, case in enumerate(cases):
        case_id = str(case.get("id") or "").strip()
        if not case_id:
            errors.append(f"cases[{index}] is missing id")
            continue
        if case_id in seen_ids:
            errors.append(f"duplicate case id: {case_id}")
        seen_ids.add(case_id)
        if case.get("requires_deep_reasoning") and not isinstance(
            case.get("answer_contract"), dict
        ):
            errors.append(f"{case_id}: deep-reasoning case must define answer_contract")
        for key in (
            "required_facts",
            "required_evidence",
            "wisdom_checks",
            "known_traps",
        ):
            _validate_rule_group(case_id, key, case.get(key), errors)
        _validate_answer_contract(case_id, case.get("answer_contract"), errors)
        if case.get("requires_deep_reasoning"):
            if not case.get("required_evidence"):
                errors.append(
                    f"{case_id}: deep-reasoning case must include required_evidence"
                )
            if not case.get("wisdom_checks"):
                errors.append(
                    f"{case_id}: deep-reasoning case must include wisdom_checks"
                )
        answers = case.get("answers")
        if answers is not None and not isinstance(answers, dict):
            errors.append(f"{case_id}: answers must be an object")
        context_tokens = case.get("context_tokens")
        if context_tokens is not None:
            if not isinstance(context_tokens, dict):
                errors.append(f"{case_id}: context_tokens must be an object")
            else:
                for label, value in context_tokens.items():
                    try:
                        if int(value or 0) < 0:
                            raise ValueError("negative")
                    except (TypeError, ValueError):
                        errors.append(
                            f"{case_id}: context_tokens[{label}] must be a non-negative int"
                        )
    if errors:
        raise ValueError("invalid quality benchmark cases: " + "; ".join(errors))


def validate_answer_overlay(overlay: dict[str, Any]) -> None:
    errors: list[str] = []
    seen_pairs: set[tuple[str, str]] = set()
    for index, item in enumerate(overlay.get("answers", [])):
        if not isinstance(item, dict):
            errors.append(f"answers[{index}] must be an object")
            continue
        case_id = str(item.get("case_id") or "").strip()
        label = str(item.get("label") or "").strip()
        if not case_id:
            errors.append(f"answers[{index}] is missing case_id")
        if not label:
            errors.append(f"answers[{index}] is missing label")
        pair = (case_id, label)
        if case_id and label and pair in seen_pairs:
            errors.append(
                f"duplicate overlay answer for case_id={case_id}, label={label}"
            )
        seen_pairs.add(pair)
        if item.get("context_tokens") is not None:
            try:
                if int(item.get("context_tokens") or 0) < 0:
                    raise ValueError("negative")
            except (TypeError, ValueError):
                errors.append(
                    f"answers[{index}].context_tokens must be a non-negative int"
                )
    if errors:
        raise ValueError("invalid answer overlay: " + "; ".join(errors))


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
    deep_reasoning_case_count = sum(
        1 for case in cases if bool(case.get("requires_deep_reasoning"))
    )
    compared_case_reports = [
        case_report
        for case_report in case_reports
        if case_report.candidate_dominates_baseline is not None
    ]
    candidate_regression_counts: dict[str, int] = {}
    for case_report in compared_case_reports:
        for dimension in case_report.candidate_regressions:
            candidate_regression_counts[dimension] = (
                candidate_regression_counts.get(dimension, 0) + 1
            )
    contract_scored_answers = [
        answer for answer in scored_answers if answer.contract_applied
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
    candidate_completeness = [
        answer.completeness
        for case_report in case_reports
        for answer in case_report.answer_scores
        if answer.label == "candidate"
    ]
    candidate_reasoning_depth = [
        answer.reasoning_depth
        for case_report in case_reports
        for answer in case_report.answer_scores
        if answer.label == "candidate"
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
            "candidate_avg_completeness": round(
                sum(candidate_completeness) / len(candidate_completeness), 4
            )
            if candidate_completeness
            else None,
            "candidate_avg_reasoning_depth": round(
                sum(candidate_reasoning_depth) / len(candidate_reasoning_depth), 4
            )
            if candidate_reasoning_depth
            else None,
            "candidate_vs_baseline_avg_delta": round(sum(deltas) / len(deltas), 1)
            if deltas
            else None,
            "avg_context_saved_pct": round(sum(saved_pcts) / len(saved_pcts), 1)
            if saved_pcts
            else None,
            "deep_reasoning_case_count": deep_reasoning_case_count,
            "compared_case_count": len(compared_case_reports),
            "candidate_dominates_baseline_case_count": sum(
                1
                for case_report in compared_case_reports
                if case_report.candidate_dominates_baseline
            ),
            "candidate_regression_case_count": sum(
                1
                for case_report in compared_case_reports
                if case_report.candidate_regressions
            ),
            "candidate_regressions_by_dimension": dict(
                sorted(candidate_regression_counts.items())
            ),
            "contract_scored_answer_count": len(contract_scored_answers),
            "contract_review_flag_count": sum(
                1 for answer in scored_answers if answer.contract_hits
            ),
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
            f"- Candidate completeness: {summary.get('candidate_avg_completeness')}",
            f"- Candidate reasoning depth: {summary.get('candidate_avg_reasoning_depth')}",
            f"- Candidate vs baseline average delta: {summary.get('candidate_vs_baseline_avg_delta')}",
            f"- Average context saved: {summary.get('avg_context_saved_pct')}%",
            f"- Deep-reasoning cases: {summary.get('deep_reasoning_case_count')}",
            f"- Compared baseline/candidate cases: {summary.get('compared_case_count')}",
            f"- Candidate dominates baseline cases: {summary.get('candidate_dominates_baseline_case_count')}",
            f"- Candidate regression cases: {summary.get('candidate_regression_case_count')}",
            f"- Contract-scored answers: {summary.get('contract_scored_answer_count')}",
            f"- Contract review flags: {summary.get('contract_review_flag_count')}",
            "",
            "## Cases",
            "",
            "| Case | TUI | Category | Answer | Score | Fact | Evidence | Wisdom | Complete | Reasoning | Trap-free | Notes |",
            "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for case in report.get("cases", []):
        for answer in case.get("answer_scores", []):
            notes = "; ".join(answer.get("notes") or [])
            lines.append(
                "| {case_id} | {tui} | {category} | {label} | {score} | {fact:.2f} | {evidence:.2f} | {wisdom:.2f} | {complete:.2f} | {reasoning:.2f} | {trap_free:.2f} | {notes} |".format(
                    case_id=case.get("id", ""),
                    tui=case.get("tui", ""),
                    category=case.get("category", ""),
                    label=answer.get("label", ""),
                    score=answer.get("score", 0),
                    fact=float(answer.get("fact_recall") or 0),
                    evidence=float(answer.get("evidence_recall") or 0),
                    wisdom=float(answer.get("wisdom") or 0),
                    complete=float(answer.get("completeness") or 0),
                    reasoning=float(answer.get("reasoning_depth") or 0),
                    trap_free=float(answer.get("trap_free") or 0),
                    notes=notes.replace("|", "/"),
                )
            )
    lines.append("")
    lines.append("## Candidate vs Baseline")
    lines.append("")
    for case in report.get("cases", []):
        regressions = [
            str(item) for item in case.get("candidate_regressions", []) if str(item)
        ]
        dominates = case.get("candidate_dominates_baseline")
        if dominates is None:
            continue
        if dominates:
            lines.append(
                f"- {case.get('id')}: candidate matched or beat baseline on scored quality dimensions."
            )
        else:
            lines.append(
                f"- {case.get('id')}: candidate regressed on {', '.join(regressions)}."
            )
    lines.append("")
    lines.append("## Review Flags")
    lines.append("")
    for case in report.get("cases", []):
        for answer in case.get("answer_scores", []):
            missing = [
                hit.get("id", "")
                for group in (
                    "fact_hits",
                    "evidence_hits",
                    "wisdom_hits",
                    "contract_hits",
                )
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
        regressions = [
            str(item) for item in case.get("candidate_regressions", []) if str(item)
        ]
        if regressions:
            lines.append(f"- {case.get('id')} / comparison:")
            lines.append(f"  - Candidate regressions: {', '.join(regressions)}")
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
