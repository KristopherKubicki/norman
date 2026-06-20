#!/usr/bin/env python3
"""Score a filled planner LLM benchmark answer packet."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from pathlib import Path
from typing import Any


SCHEMA = "norman.planner-llm-benchmark-score.v1"
DEFAULT_PACKET_JSON = Path(
    "/tmp/norman_tui_benchmarks/planner_llm_benchmark_packet.json"
)
DEFAULT_ANSWERS_JSON = Path(
    "/tmp/norman_tui_benchmarks/planner_llm_benchmark_answers.template.json"
)
DEFAULT_OUTPUT_JSON = Path(
    "/tmp/norman_tui_benchmarks/planner_llm_benchmark_score.json"
)
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_benchmarks/planner_llm_benchmark_score.md")

CONTRACT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("route_decision", ("route", "decision", "pre-route", "candidate")),
    ("evidence_required", ("evidence", "artifact", "command", "receipt")),
    ("accounting_cost_note", ("cost", "accounting", "ledger", "usd")),
    ("authority_boundary", ("authority", "boundary", "human", "frontier")),
    ("next_action", ("next action", "next step", "checkpoint", "blocker")),
)
ACCEPTED_VERIFIER_VALUES = {"accepted", "accept", "pass", "passed", "true", "yes"}
REJECTED_VERIFIER_VALUES = {"rejected", "reject", "fail", "failed", "false", "no"}
HEALTHY_RUNTIME_VALUES = {"healthy", "ok", "ready", "available", "online"}
UNHEALTHY_RUNTIME_VALUES = {"unhealthy", "unavailable", "offline", "dead", "missing"}


def _lower_words(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _term_hit(text: str, term: str) -> bool:
    return _lower_words(term) in _lower_words(text)


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _case_by_id(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(case["case_id"]): case for case in packet.get("cases", [])}


def _prompt_by_id(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(prompt["prompt_id"]): prompt for prompt in packet.get("prompts", [])}


def _model_by_id(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(model["route_id"]): model for model in packet.get("models", [])}


def _contract_hits(answer_text: str) -> dict[str, bool]:
    lowered = _lower_words(answer_text)
    return {
        label: any(pattern in lowered for pattern in patterns)
        for label, patterns in CONTRACT_PATTERNS
    }


def _verifier_acceptance_score(value: Any) -> tuple[float, bool]:
    normalized = _lower_words(str(value or ""))
    if normalized in ACCEPTED_VERIFIER_VALUES:
        return 1.0, False
    if normalized in REJECTED_VERIFIER_VALUES:
        return 0.0, True
    return 0.0, False


def _runtime_health_issue(model: dict[str, Any], answer: dict[str, Any]) -> bool:
    requires_health = bool(
        model.get("accounting", {}).get("requires_runtime_health")
        or model.get("provider_surface") == "local-dgx-spark"
    )
    if not requires_health:
        return False
    status = _lower_words(str(answer.get("runtime_health_status") or ""))
    return status not in HEALTHY_RUNTIME_VALUES


def score_answer(
    answer: dict[str, Any],
    *,
    case: dict[str, Any],
    prompt: dict[str, Any],
    model: dict[str, Any],
) -> dict[str, Any]:
    answer_text = str(answer.get("answer") or "")
    required_terms = [str(term) for term in prompt.get("required_terms", [])]
    forbidden_terms = [str(term) for term in prompt.get("forbidden_terms", [])]
    required_hits = [term for term in required_terms if _term_hit(answer_text, term)]
    forbidden_hits = [term for term in forbidden_terms if _term_hit(answer_text, term)]
    contract_hits = _contract_hits(answer_text)
    verifier_score, verifier_rejected = _verifier_acceptance_score(
        answer.get("verifier_acceptance")
    )
    metric_fields_present = {
        "answer": bool(answer_text.strip()),
        "input_tokens": _coerce_int(answer.get("input_tokens")) > 0,
        "output_tokens": _coerce_int(answer.get("output_tokens")) > 0,
        "latency_ms": _coerce_int(answer.get("latency_ms")) > 0,
        "runtime_health_status": bool(str(answer.get("runtime_health_status") or "")),
        "verifier_acceptance": bool(str(answer.get("verifier_acceptance") or "")),
    }
    required_recall = (
        len(required_hits) / len(required_terms) if required_terms else 1.0
    )
    contract_score = sum(1 for hit in contract_hits.values() if hit) / len(
        contract_hits
    )
    metrics_score = sum(1 for hit in metric_fields_present.values() if hit) / len(
        metric_fields_present
    )
    forbidden_score = 0.0 if forbidden_hits else 1.0
    runtime_issue = _runtime_health_issue(model, answer)
    critical_fail_reasons = []
    if not answer_text.strip():
        critical_fail_reasons.append("missing_answer")
    if forbidden_hits:
        critical_fail_reasons.append("forbidden_terms")
    if verifier_rejected:
        critical_fail_reasons.append("verifier_rejected")
    if runtime_issue:
        critical_fail_reasons.append("runtime_health_not_healthy")
    weighted_score = (
        required_recall * 0.42
        + contract_score * 0.24
        + forbidden_score * 0.16
        + verifier_score * 0.10
        + metrics_score * 0.08
    )
    if critical_fail_reasons:
        weighted_score = min(weighted_score, 0.49)
    return {
        "prompt_id": prompt["prompt_id"],
        "case_id": case["case_id"],
        "candidate_id": model["route_id"],
        "account_scope": case["account_scope"],
        "family": case["family"],
        "case_weight": _coerce_float(case.get("promotion_weight")) or 1.0,
        "score": round(max(0.0, min(1.0, weighted_score)), 4),
        "required_terms_hit": required_hits,
        "required_terms_missing": [
            term for term in required_terms if term not in required_hits
        ],
        "forbidden_terms_hit": forbidden_hits,
        "contract_hits": contract_hits,
        "metric_fields_present": metric_fields_present,
        "runtime_health_status": str(answer.get("runtime_health_status") or ""),
        "verifier_acceptance": str(answer.get("verifier_acceptance") or ""),
        "critical_fail_reasons": critical_fail_reasons,
        "estimated_usd": _coerce_float(answer.get("estimated_usd")),
        "latency_ms": _coerce_int(answer.get("latency_ms")),
        "input_tokens": _coerce_int(answer.get("input_tokens")),
        "cached_input_tokens": _coerce_int(answer.get("cached_input_tokens")),
        "output_tokens": _coerce_int(answer.get("output_tokens")),
    }


def _account_cases(rows: list[dict[str, Any]], account: str) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row["account_scope"] == account or row["account_scope"] == "both"
    ]


def _weighted_average(rows: list[dict[str, Any]]) -> float:
    total_weight = sum(float(row["case_weight"]) for row in rows)
    if total_weight <= 0:
        return 0.0
    return sum(float(row["score"]) * float(row["case_weight"]) for row in rows) / (
        total_weight
    )


def _json_contract_success_rate(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    passed = 0
    for row in rows:
        metrics = row["metric_fields_present"]
        if all(metrics.values()) and not row["forbidden_terms_hit"]:
            passed += 1
    return passed / len(rows)


def _role_promotions(
    *,
    rows: list[dict[str, Any]],
    policy: dict[str, Any],
    account: str,
    model: dict[str, Any],
) -> list[dict[str, Any]]:
    roles = policy.get("local_model_roles", {})
    weighted_score = round(_weighted_average(rows), 4)
    critical_failure_count = sum(1 for row in rows if row["critical_fail_reasons"])
    json_contract_success_rate = round(_json_contract_success_rate(rows), 4)
    verifier_accept_count = sum(
        1
        for row in rows
        if _lower_words(row["verifier_acceptance"]) in ACCEPTED_VERIFIER_VALUES
    )
    authority_preserved_count = sum(
        1 for row in rows if row["contract_hits"].get("authority_boundary")
    )
    promotions = []
    for role, gate in roles.items():
        if role == "final_authority":
            promotions.append(
                {
                    "role": role,
                    "promoted": False,
                    "reason": gate.get("reason", "final authority disabled"),
                }
            )
            continue
        allowed_accounts = set(gate.get("allowed_accounts") or ("personal", "work"))
        blockers = []
        if account not in allowed_accounts:
            blockers.append("account_not_allowed")
        if weighted_score < float(gate.get("min_weighted_score") or 1.0):
            blockers.append("score_below_threshold")
        if critical_failure_count > int(gate.get("critical_failure_count") or 0):
            blockers.append("critical_failures")
        min_json = float(gate.get("json_contract_success_rate") or 0.0)
        if json_contract_success_rate < min_json:
            blockers.append("json_contract_success_rate")
        if gate.get("requires_deterministic_validator") and verifier_accept_count < len(
            rows
        ):
            blockers.append("deterministic_validator_not_all_accepted")
        if gate.get("cloud_verifier_required") and verifier_accept_count < len(rows):
            blockers.append("cloud_verifier_not_all_accepted")
        if authority_preserved_count < len(rows):
            blockers.append("authority_boundary_not_all_preserved")
        promotions.append(
            {
                "role": role,
                "promoted": not blockers,
                "blockers": blockers,
                "weighted_score": weighted_score,
                "min_weighted_score": gate.get("min_weighted_score"),
                "critical_failure_count": critical_failure_count,
                "json_contract_success_rate": json_contract_success_rate,
                "verifier_acceptance_rate": round(verifier_accept_count / len(rows), 4)
                if rows
                else 0.0,
                "authority_boundary_preserved_rate": round(
                    authority_preserved_count / len(rows), 4
                )
                if rows
                else 0.0,
            }
        )
    return promotions


def _promotion_records(
    rows: list[dict[str, Any]],
    *,
    packet: dict[str, Any],
    model_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    policy = packet.get("promotion_policy", {})
    records = []
    candidate_ids = sorted({row["candidate_id"] for row in rows})
    for candidate_id in candidate_ids:
        model = model_by_id.get(candidate_id, {})
        if model.get("provider_surface") != "local-dgx-spark":
            continue
        candidate_rows = [row for row in rows if row["candidate_id"] == candidate_id]
        for account in ("personal", "work"):
            scoped_rows = _account_cases(candidate_rows, account)
            if not scoped_rows:
                continue
            role_promotions = _role_promotions(
                rows=scoped_rows,
                policy=policy,
                account=account,
                model=model,
            )
            records.append(
                {
                    "schema": "norman.local-model-promotion-record.v1",
                    "candidate_id": candidate_id,
                    "account_scope": account,
                    "runtime": model.get("runtime"),
                    "provider_surface": model.get("provider_surface"),
                    "case_count": len(scoped_rows),
                    "weighted_score": round(_weighted_average(scoped_rows), 4),
                    "critical_failure_count": sum(
                        1 for row in scoped_rows if row["critical_fail_reasons"]
                    ),
                    "estimated_usd": round(
                        sum(float(row["estimated_usd"]) for row in scoped_rows), 6
                    ),
                    "median_latency_ms": int(
                        statistics.median(row["latency_ms"] for row in scoped_rows)
                    ),
                    "roles": role_promotions,
                    "planner_consumption_allowed_roles": [
                        role["role"]
                        for role in role_promotions
                        if role.get("promoted") is True
                    ],
                }
            )
    return records


def build_report(packet: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    prompts = _prompt_by_id(packet)
    cases = _case_by_id(packet)
    models = _model_by_id(packet)
    answer_rows = answers.get("answers") if isinstance(answers, dict) else []
    scored_rows = []
    missing_prompt_count = 0
    for answer in answer_rows or []:
        prompt_id = str(answer.get("prompt_id") or "")
        prompt = prompts.get(prompt_id)
        if not prompt:
            missing_prompt_count += 1
            continue
        case = cases[str(prompt["case_id"])]
        model = models[str(prompt["candidate_id"])]
        scored_rows.append(score_answer(answer, case=case, prompt=prompt, model=model))
    promotion_records = _promotion_records(
        scored_rows, packet=packet, model_by_id=models
    )
    scores = [float(row["score"]) for row in scored_rows]
    critical_rows = [row for row in scored_rows if row["critical_fail_reasons"]]
    summary = {
        "answer_count": len(scored_rows),
        "expected_prompt_count": len(prompts),
        "missing_or_unknown_prompt_count": len(prompts)
        - len(scored_rows)
        + missing_prompt_count,
        "critical_failure_count": len(critical_rows),
        "avg_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "local_promotion_record_count": len(promotion_records),
        "local_promoted_role_count": sum(
            len(record["planner_consumption_allowed_roles"])
            for record in promotion_records
        ),
        "total_estimated_usd": round(
            sum(float(row["estimated_usd"]) for row in scored_rows), 6
        ),
        "gate": "pass" if scored_rows and not critical_rows else "fail",
    }
    return {
        "schema": SCHEMA,
        "generated_at": int(time.time()),
        "packet_schema": packet.get("schema"),
        "answers_schema": answers.get("schema"),
        "run_id": answers.get("run_id"),
        "runner": answers.get("runner"),
        "environment": answers.get("environment"),
        "summary": summary,
        "promotion_records": promotion_records,
        "scores": scored_rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Planner LLM Benchmark Score",
        "",
        f"- Run: `{report.get('run_id')}`",
        f"- Runner: `{report.get('runner')}`",
        f"- Gate: `{summary['gate']}`",
        f"- Answers scored: `{summary['answer_count']}` / `{summary['expected_prompt_count']}`",
        f"- Average score: `{summary['avg_score']}`",
        f"- Critical failures: `{summary['critical_failure_count']}`",
        f"- Local promotion records: `{summary['local_promotion_record_count']}`",
        f"- Local promoted roles: `{summary['local_promoted_role_count']}`",
        f"- Total estimated run cost: `${summary['total_estimated_usd']:.6f}`",
        "",
        "## Local Promotion Records",
        "",
        "| Candidate | Account | Score | Critical failures | Allowed roles |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for record in report.get("promotion_records", []):
        lines.append(
            "| {candidate} | {account} | {score:.4f} | {failures} | {roles} |".format(
                candidate=record["candidate_id"],
                account=record["account_scope"],
                score=float(record["weighted_score"]),
                failures=record["critical_failure_count"],
                roles=", ".join(record["planner_consumption_allowed_roles"]) or "-",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet-json", type=Path, default=DEFAULT_PACKET_JSON)
    parser.add_argument("--answers-json", type=Path, default=DEFAULT_ANSWERS_JSON)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = json.loads(args.packet_json.read_text(encoding="utf-8"))
    answers = json.loads(args.answers_json.read_text(encoding="utf-8"))
    report = build_report(packet, answers)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": report["schema"],
                "output_json": str(args.output_json),
                "output_md": str(args.output_md),
                "summary": report["summary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
