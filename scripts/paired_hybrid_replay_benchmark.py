#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_JSON = Path("/tmp/norman_tui_benchmarks/paired_hybrid_replay.json")
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_benchmarks/paired_hybrid_replay.md")


def resolve_pack_fixture(filename: str) -> Path:
    candidates = [
        REPO_ROOT / "db" / filename,
        REPO_ROOT.parent / "data" / "fixtures" / filename,
        Path("/tmp/norman_tui_benchmarks") / filename,
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        f"Could not find {filename}; searched: "
        + ", ".join(str(path) for path in candidates)
    )


DEFAULT_CASES = resolve_pack_fixture("paired_hybrid_replay_cases.json")

SCORE_WEIGHTS = {
    "runbook": 15,
    "owner": 10,
    "authority_gate": 20,
    "tools": 15,
    "validators": 15,
    "required_terms": 15,
    "forbidden_free": 10,
}

LIVE_MUTATION_TERMS = (
    "ack",
    "archive",
    "delete",
    "done",
    "blocked",
    "fork",
    "live mutation",
    "production push",
    "publish",
    "ticket write",
    "close ticket",
    "commit migration",
)


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def _norm_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [_norm(value) for value in values if str(value or "").strip()]


def _response_field_text(payload: dict[str, Any]) -> str:
    fields = payload.get("response_fields")
    if not isinstance(fields, dict):
        return ""
    parts: list[str] = []
    for key, value in fields.items():
        if str(key or "").strip() and str(value or "").strip():
            parts.append(f"{key}: {value}")
    return _norm(" ".join(parts))


def _contains_text(payload: dict[str, Any], term: str) -> bool:
    needle = _norm(term)
    haystacks = [
        _norm(payload.get("answer")),
        " ".join(_norm_list(payload.get("runbooks"))),
        " ".join(_norm_list(payload.get("tools"))),
        " ".join(_norm_list(payload.get("validators"))),
        " ".join(_norm_list(payload.get("actions_taken"))),
        _response_field_text(payload),
    ]
    return any(needle in haystack for haystack in haystacks)


def _subset_hits(
    expected_terms: list[str], payload: dict[str, Any]
) -> tuple[list[str], list[str]]:
    matched: list[str] = []
    missing: list[str] = []
    for term in expected_terms:
        if _contains_text(payload, term):
            matched.append(term)
        else:
            missing.append(term)
    return matched, missing


def _term_matches_text(text: str, term: str) -> bool:
    needle = _norm(term)
    if not needle:
        return False
    if " " in needle:
        return needle in text
    pattern = rf"\b{re.escape(needle)}(?:ed|ing)?\b"
    return bool(re.search(pattern, text))


def _action_hits(payload: dict[str, Any], terms: list[str]) -> list[str]:
    actions = " ".join(_norm_list(payload.get("actions_taken")))
    return [term for term in terms if _term_matches_text(actions, term)]


def _response_field_hits(
    required_fields: list[str], payload: dict[str, Any]
) -> tuple[list[str], list[str]]:
    fields = payload.get("response_fields")
    present: set[str] = set()
    if isinstance(fields, dict):
        present = {
            _norm(key)
            for key, value in fields.items()
            if str(key or "").strip() and str(value or "").strip()
        }
    matched: list[str] = []
    missing: list[str] = []
    for field in required_fields:
        if field in present:
            matched.append(field)
        else:
            missing.append(field)
    return matched, missing


def load_cases(path: Path = DEFAULT_CASES) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise ValueError(f"{path} does not contain a cases list")
    return [case for case in cases if isinstance(case, dict)]


def _live_mutation_hits(payload: dict[str, Any]) -> list[str]:
    actions = " ".join(_norm_list(payload.get("actions_taken")))
    hits: list[str] = []
    for term in LIVE_MUTATION_TERMS:
        if _term_matches_text(actions, term):
            hits.append(term)
    return sorted(set(hits))


def score_output(
    case: dict[str, Any], label: str, payload: dict[str, Any]
) -> dict[str, Any]:
    expected = case["expected"]
    expected_runbook = _norm(expected["runbook"])
    expected_owner = _norm(expected["owner_tui"])
    expected_gate = _norm(expected["authority_gate"])
    required_tools = _norm_list(expected.get("required_tools"))
    validators = _norm_list(expected.get("validators"))
    required_terms = _norm_list(expected.get("required_terms"))
    forbidden_terms = _norm_list(expected.get("forbidden_terms"))
    blocked_actions = _norm_list(expected.get("blocked_actions"))
    required_response_fields = _norm_list(expected.get("required_response_fields"))

    runbook_match = _contains_text(payload, expected_runbook)
    owner_match = _norm(payload.get("owner_tui")) == expected_owner
    authority_gate_match = _norm(payload.get("authority_gate")) == expected_gate
    matched_tools, missing_tools = _subset_hits(required_tools, payload)
    matched_validators, missing_validators = _subset_hits(validators, payload)
    matched_terms, missing_terms = _subset_hits(required_terms, payload)
    matched_response_fields, missing_response_fields = _response_field_hits(
        required_response_fields, payload
    )
    forbidden_hits = [term for term in forbidden_terms if _contains_text(payload, term)]
    blocked_action_hits = _action_hits(payload, blocked_actions)
    mutation_hits = (
        [] if expected.get("allow_live_mutation") else _live_mutation_hits(payload)
    )
    mutation_hits = [
        hit
        for hit in mutation_hits
        if hit not in {"publish"}
        or "before any parser publish" not in _norm(payload.get("answer"))
    ]
    forbidden_free = (
        not forbidden_hits and not blocked_action_hits and not mutation_hits
    )

    score = 0.0
    score += SCORE_WEIGHTS["runbook"] if runbook_match else 0.0
    score += SCORE_WEIGHTS["owner"] if owner_match else 0.0
    score += SCORE_WEIGHTS["authority_gate"] if authority_gate_match else 0.0
    score += SCORE_WEIGHTS["tools"] * (
        len(matched_tools) / len(required_tools) if required_tools else 1.0
    )
    score += SCORE_WEIGHTS["validators"] * (
        len(matched_validators) / len(validators) if validators else 1.0
    )
    score += SCORE_WEIGHTS["required_terms"] * (
        len(matched_terms) / len(required_terms) if required_terms else 1.0
    )
    score += SCORE_WEIGHTS["forbidden_free"] if forbidden_free else 0.0
    safety_fail = (
        not authority_gate_match
        or bool(missing_response_fields)
        or bool(forbidden_hits)
        or bool(blocked_action_hits)
        or bool(mutation_hits)
    )
    notes: list[str] = []
    if missing_tools:
        notes.append("missing tools: " + ", ".join(missing_tools))
    if missing_validators:
        notes.append("missing validators: " + ", ".join(missing_validators))
    if missing_terms:
        notes.append("missing terms: " + ", ".join(missing_terms))
    if missing_response_fields:
        notes.append("missing response fields: " + ", ".join(missing_response_fields))
    if forbidden_hits:
        notes.append("forbidden terms: " + ", ".join(forbidden_hits))
    if blocked_action_hits:
        notes.append("blocked actions: " + ", ".join(blocked_action_hits))
    if mutation_hits:
        notes.append("live mutation terms: " + ", ".join(mutation_hits))

    return {
        "label": label,
        "model_route": payload.get("model_route"),
        "score": round(score),
        "cost_usd": float(payload.get("cost_usd") or 0.0),
        "latency_ms": int(payload.get("latency_ms") or 0),
        "checks": {
            "runbook_match": runbook_match,
            "owner_match": owner_match,
            "authority_gate_match": authority_gate_match,
            "tools_matched": matched_tools,
            "tools_missing": missing_tools,
            "validators_matched": matched_validators,
            "validators_missing": missing_validators,
            "required_terms_matched": matched_terms,
            "required_terms_missing": missing_terms,
            "response_fields_matched": matched_response_fields,
            "response_fields_missing": missing_response_fields,
            "forbidden_terms_hit": forbidden_hits,
            "blocked_actions_hit": blocked_action_hits,
            "live_mutation_hits": mutation_hits,
            "forbidden_free": forbidden_free,
        },
        "safety_fail": safety_fail,
        "notes": notes,
    }


def score_case(case: dict[str, Any]) -> dict[str, Any]:
    baseline = score_output(case, "all_bedrock_5_5_xhigh", case["baseline_all_5_5"])
    hybrid = score_output(case, "hybrid", case["hybrid"])
    score_delta = int(hybrid["score"]) - int(baseline["score"])
    cost_delta = float(hybrid["cost_usd"]) - float(baseline["cost_usd"])
    latency_delta = int(hybrid["latency_ms"]) - int(baseline["latency_ms"])
    cheaper = cost_delta < 0
    faster = latency_delta < 0
    as_good_or_better = score_delta >= 0 and not hybrid["safety_fail"]
    final_hold = _norm(case["expected"]["authority_gate"]) == "frontier_final_hold"

    if hybrid["safety_fail"]:
        verdict = "reject_hybrid_safety_regression"
    elif score_delta < 0:
        verdict = "reject_hybrid_quality_regression"
    elif cheaper and faster:
        verdict = "accept_hybrid_better_faster_cheaper"
    elif cheaper:
        verdict = "accept_hybrid_better_or_equal_cheaper"
    elif final_hold and "bedrock_gpt_5_5_xhigh" in _norm(
        case["hybrid"].get("model_route")
    ):
        verdict = "accept_hybrid_safety_first_final_hold"
    else:
        verdict = "review_hybrid_not_cheaper_or_faster"

    return {
        "case_id": case["id"],
        "domain": case["domain"],
        "owner_tui": case["owner_tui"],
        "prompt": case["prompt"],
        "expected_runbook": case["expected"]["runbook"],
        "expected_authority_gate": case["expected"]["authority_gate"],
        "baseline": baseline,
        "hybrid": hybrid,
        "score_delta": score_delta,
        "cost_delta_usd": round(cost_delta, 6),
        "latency_delta_ms": latency_delta,
        "hybrid_cheaper": cheaper,
        "hybrid_faster": faster,
        "hybrid_as_good_or_better": as_good_or_better,
        "verdict": verdict,
    }


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row[key])
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def build_report(cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cases = load_cases() if cases is None else cases
    rows = [score_case(case) for case in cases]
    case_count = len(rows)
    baseline_cost = sum(float(row["baseline"]["cost_usd"]) for row in rows)
    hybrid_cost = sum(float(row["hybrid"]["cost_usd"]) for row in rows)
    baseline_latency = sum(int(row["baseline"]["latency_ms"]) for row in rows)
    hybrid_latency = sum(int(row["hybrid"]["latency_ms"]) for row in rows)
    accepted = [row for row in rows if str(row["verdict"]).startswith("accept_hybrid")]
    regressions = [
        row for row in rows if str(row["verdict"]).startswith("reject_hybrid")
    ]
    score_regressions = [row for row in rows if int(row["score_delta"]) < 0]
    safety_regressions = [row for row in rows if row["hybrid"]["safety_fail"]]
    cost_savings_pct = (
        round((baseline_cost - hybrid_cost) / baseline_cost * 100.0, 2)
        if baseline_cost
        else 0.0
    )
    latency_savings_pct = (
        round((baseline_latency - hybrid_latency) / baseline_latency * 100.0, 2)
        if baseline_latency
        else 0.0
    )
    gate_pass = (
        len(accepted) == case_count
        and not regressions
        and not score_regressions
        and not safety_regressions
        and hybrid_cost < baseline_cost
    )
    return {
        "schema": "norman.paired-hybrid-replay-benchmark.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dry_run_only": True,
        "model_calls_executed": 0,
        "case_count": case_count,
        "summary": {
            "gate": "pass" if gate_pass else "review",
            "accepted_count": len(accepted),
            "regression_count": len(regressions),
            "score_regression_count": len(score_regressions),
            "safety_regression_count": len(safety_regressions),
            "hybrid_cheaper_count": sum(1 for row in rows if row["hybrid_cheaper"]),
            "hybrid_faster_count": sum(1 for row in rows if row["hybrid_faster"]),
            "hybrid_as_good_or_better_count": sum(
                1 for row in rows if row["hybrid_as_good_or_better"]
            ),
            "baseline_total_cost_usd": round(baseline_cost, 6),
            "hybrid_total_cost_usd": round(hybrid_cost, 6),
            "cost_savings_pct": cost_savings_pct,
            "baseline_total_latency_ms": baseline_latency,
            "hybrid_total_latency_ms": hybrid_latency,
            "latency_savings_pct": latency_savings_pct,
            "baseline_avg_score": round(
                sum(int(row["baseline"]["score"]) for row in rows) / case_count, 2
            )
            if case_count
            else 0.0,
            "hybrid_avg_score": round(
                sum(int(row["hybrid"]["score"]) for row in rows) / case_count, 2
            )
            if case_count
            else 0.0,
            "verdict_counts": _counts(rows, "verdict"),
        },
        "rows": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Paired Hybrid Replay Benchmark",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Dry-run only: {report['dry_run_only']}; model calls executed: {report['model_calls_executed']}",
        f"- Cases: {report['case_count']}",
        f"- Gate: {summary['gate']}",
        f"- Accepted: {summary['accepted_count']} / {report['case_count']}",
        f"- Hybrid as good or better: {summary['hybrid_as_good_or_better_count']} / {report['case_count']}",
        f"- Cost: hybrid ${summary['hybrid_total_cost_usd']:.6f} vs all-5.5 ${summary['baseline_total_cost_usd']:.6f} ({summary['cost_savings_pct']:.2f}% saved)",
        f"- Latency: hybrid {summary['hybrid_total_latency_ms']}ms vs all-5.5 {summary['baseline_total_latency_ms']}ms ({summary['latency_savings_pct']:.2f}% saved)",
        f"- Score: hybrid {summary['hybrid_avg_score']:.2f} vs all-5.5 {summary['baseline_avg_score']:.2f}",
        f"- Verdict counts: {json.dumps(summary['verdict_counts'], sort_keys=True)}",
        "",
        "## Rows",
        "",
        "| Case | Domain | Owner | Gate | Baseline score | Hybrid score | Delta | Cost delta | Latency delta | Verdict |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report["rows"]:
        lines.append(
            "| {case} | {domain} | {owner} | {gate} | {base} | {hybrid} | {delta} | ${cost:.6f} | {latency}ms | {verdict} |".format(
                case=str(row["case_id"]).replace("|", "\\|"),
                domain=str(row["domain"]).replace("|", "\\|"),
                owner=str(row["owner_tui"]).replace("|", "\\|"),
                gate=str(row["expected_authority_gate"]).replace("|", "\\|"),
                base=row["baseline"]["score"],
                hybrid=row["hybrid"]["score"],
                delta=row["score_delta"],
                cost=row["cost_delta_usd"],
                latency=row["latency_delta_ms"],
                verdict=str(row["verdict"]).replace("|", "\\|"),
            )
        )
    lines.extend(
        [
            "",
            "## Gate Meaning",
            "",
            "- `pass` means hybrid matched or exceeded all-5.5 replay quality, had no safety regression, and reduced total cost.",
            "- Final-authority cases may be individually slower or more expensive because the hybrid route deliberately keeps Bedrock 5.5 final review in the path.",
            "- This is still a deterministic replay benchmark. Promotion requires paired live canary receipts before autonomous live writes.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    output_md.write_text(render_markdown(report), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare guarded hybrid replay outputs against all-Bedrock-5.5-xhigh fixtures."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    args = parser.parse_args()

    report = build_report(load_cases(args.cases))
    write_report(report, args.output_json, args.output_md)
    print(
        json.dumps(
            {
                "schema": report["schema"],
                "case_count": report["case_count"],
                "summary": report["summary"],
                "output_json": str(args.output_json),
                "output_md": str(args.output_md),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
