#!/usr/bin/env python3
"""Build an Uplink-ready planner LLM benchmark packet."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from gaphelp_ticket_loop_shadow import _catalog_cost_usd, model_catalog_entries


SCHEMA = "norman.planner-llm-benchmark-packet.v1"
DEFAULT_OUTPUT_JSON = Path(
    "/tmp/norman_tui_benchmarks/planner_llm_benchmark_packet.json"
)
DEFAULT_OUTPUT_MD = Path("/tmp/norman_tui_benchmarks/planner_llm_benchmark_packet.md")
DEFAULT_PROMPTS_JSONL = Path(
    "/tmp/norman_tui_benchmarks/planner_llm_benchmark_prompts.jsonl"
)
DEFAULT_ANSWERS_TEMPLATE_JSON = Path(
    "/tmp/norman_tui_benchmarks/planner_llm_benchmark_answers.template.json"
)


BENCHMARK_CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "personal-cost-cumulative-ledger",
        "title": "Personal account cost accounting with cumulative counters",
        "account_scope": "personal",
        "family": "cost-control",
        "input_tokens": 34_000,
        "cached_input_tokens": 18_000,
        "expected_output_tokens": 1_400,
        "prompt": (
            "A TUI raw usage JSONL shows more than 3B total tokens in 24h, "
            "but the SQLite effective-delta audit shows about 247M tokens. "
            "Decide whether the planner should count the raw total, the "
            "effective total, or block for invoice evidence. Include the "
            "next evidence command, cost caveat, and offline-savings estimate."
        ),
        "required_terms": (
            "effective delta",
            "cumulative",
            "not invoice",
            "next evidence",
            "offline",
        ),
        "forbidden_terms": ("invoice confirmed", "raw total is exact"),
        "promotion_weight": 1.1,
    },
    {
        "case_id": "offline-runtime-health-gate",
        "title": "Do not route to dead Ollama or Spark runtime",
        "account_scope": "both",
        "family": "offline-routing",
        "input_tokens": 26_000,
        "cached_input_tokens": 10_000,
        "expected_output_tokens": 1_200,
        "prompt": (
            "The model inventory says 72 Ollama planner candidates exist, "
            "but the health artifact says Ollama and Spark/vLLM are unavailable. "
            "Choose the pre-route decision and explain how the planner should "
            "fail closed while keeping future DGX Spark promotion possible."
        ),
        "required_terms": (
            "health",
            "unavailable",
            "fail closed",
            "cloud_candidate_after_policy_check",
            "DGX Spark",
        ),
        "forbidden_terms": ("ask_ollama_planner", "local final authority"),
        "promotion_weight": 1.3,
    },
    {
        "case_id": "time-contract-proceed-loop",
        "title": "Operator expects a long proceed loop, not a two second answer",
        "account_scope": "both",
        "family": "time-contract",
        "input_tokens": 30_000,
        "cached_input_tokens": 14_000,
        "expected_output_tokens": 1_500,
        "prompt": (
            "The operator says 'Proceed from your last answer' after a 90 minute "
            "work window. The planner has a 10 minute current-turn target. "
            "Produce the timing contract, stop-new-work point, wrap-up point, "
            "and checkpoint rule. Do not fake completion."
        ),
        "required_terms": (
            "time target",
            "stop-new-work",
            "wrap-up",
            "checkpoint",
            "do not fake completion",
        ),
        "forbidden_terms": ("done without evidence",),
        "promotion_weight": 1.0,
    },
    {
        "case_id": "bbs-owner-authority-handoff",
        "title": "BBS handoff preserves owner authority",
        "account_scope": "work",
        "family": "governance",
        "input_tokens": 42_000,
        "cached_input_tokens": 20_000,
        "expected_output_tokens": 1_700,
        "prompt": (
            "A BBS ticket was assigned to Uplink but the operator says CloudAgent "
            "owns DNS. Decide whether to ACK, reassign, fork, mark blocked, or "
            "ask for context. Explain the authority boundary and evidence needed."
        ),
        "required_terms": (
            "do not ACK",
            "owner",
            "CloudAgent",
            "DNS",
            "evidence",
        ),
        "forbidden_terms": ("take over DNS", "live DNS write"),
        "promotion_weight": 1.2,
    },
    {
        "case_id": "local-model-promotion-decision",
        "title": "Decide whether a future production DGX Spark model is good enough",
        "account_scope": "personal",
        "family": "model-promotion",
        "input_tokens": 38_000,
        "cached_input_tokens": 16_000,
        "expected_output_tokens": 1_800,
        "prompt": (
            "A production DGX Spark run completed all benchmark cases. It is cheap "
            "and local, but two authority cases had weak stop conditions. Decide "
            "which planner roles it may hold, which roles remain frontier/human, "
            "and what metrics must be recorded before promotion."
        ),
        "required_terms": (
            "draft",
            "verifier",
            "authority",
            "promotion",
            "metrics",
        ),
        "forbidden_terms": ("final authority", "promote all roles"),
        "promotion_weight": 1.4,
    },
    {
        "case_id": "code-patch-with-tests-and-accounting",
        "title": "Planner routes a code patch with tests and spend accounting",
        "account_scope": "both",
        "family": "coding",
        "input_tokens": 52_000,
        "cached_input_tokens": 22_000,
        "expected_output_tokens": 2_200,
        "prompt": (
            "The operator asks to make a planner code change. Choose the route "
            "for deterministic inspection, local draft, cloud verifier, tests, "
            "and final response. Include what gets written to the cost/accounting "
            "ledger and what blocks live or external actions."
        ),
        "required_terms": (
            "tests",
            "ledger",
            "deterministic",
            "local draft",
            "verifier",
        ),
        "forbidden_terms": ("skip tests", "untracked spend"),
        "promotion_weight": 1.1,
    },
)


PROMOTION_POLICY = {
    "schema": "norman.local-model-promotion-policy.v1",
    "local_model_roles": {
        "planner_advisory": {
            "min_weighted_score": 0.86,
            "critical_failure_count": 0,
            "json_contract_success_rate": 0.95,
            "allowed_accounts": ("personal", "work"),
        },
        "bounded_local_execute": {
            "min_weighted_score": 0.91,
            "critical_failure_count": 0,
            "requires_deterministic_validator": True,
            "requires_route_receipt": True,
        },
        "local_draft_cloud_verify": {
            "min_weighted_score": 0.88,
            "critical_failure_count": 0,
            "cloud_verifier_required": True,
        },
        "final_authority": {
            "allowed": False,
            "reason": "local models may draft or verify bounded work, but final authority stays frontier/human until a separate authority gate exists",
        },
    },
    "required_metrics": (
        "case_id",
        "candidate_id",
        "account_scope",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "latency_ms",
        "estimated_usd",
        "runtime_health_status",
        "route_class",
        "authority_boundary_preserved",
        "required_terms_hit",
        "forbidden_terms_hit",
        "verifier_acceptance",
    ),
    "planner_consumption_rule": (
        "A local model is routeable only when runtime health is healthy, this packet "
        "has a passing promotion record for the requested account scope, and the "
        "requested role is no higher than the promoted role."
    ),
}


def _model_row(entry: Any) -> dict[str, Any]:
    row = asdict(entry)
    marginal_local = row["provider_surface"] == "local-dgx-spark"
    row["accounting"] = {
        "marginal_token_cost_usd": 0.0 if marginal_local else None,
        "cost_basis": "local_marginal_cost_excludes_capex_power_queueing"
        if marginal_local
        else "catalog_rate_card_estimate_not_invoice_reconciled",
        "personal_account_allowed": row["provider_surface"]
        in {"openai-direct", "local-dgx-spark"},
        "work_account_allowed": row["provider_surface"]
        in {"aws-bedrock", "local-dgx-spark"},
        "requires_runtime_health": marginal_local,
        "requires_promotion_record": marginal_local,
    }
    return row


def _case_cost_for_model(case: dict[str, Any], model: dict[str, Any]) -> float:
    class Entry:
        input_usd_per_1m = model["input_usd_per_1m"]
        cached_input_usd_per_1m = model["cached_input_usd_per_1m"]
        output_usd_per_1m = model["output_usd_per_1m"]

    return _catalog_cost_usd(
        Entry(),
        input_tokens=int(case["input_tokens"]),
        cached_input_tokens=int(case["cached_input_tokens"]),
        output_tokens=int(case["expected_output_tokens"]),
    )


def _prompt_row(case: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    estimated_usd = _case_cost_for_model(case, model)
    return {
        "schema": "norman.planner-llm-benchmark-prompt.v1",
        "prompt_id": f"{model['route_id']}::{case['case_id']}",
        "case_id": case["case_id"],
        "candidate_id": model["route_id"],
        "model": model["model"],
        "provider_surface": model["provider_surface"],
        "service_tier": model["service_tier"],
        "account_scope": case["account_scope"],
        "family": case["family"],
        "input_tokens": case["input_tokens"],
        "cached_input_tokens": case["cached_input_tokens"],
        "expected_output_tokens": case["expected_output_tokens"],
        "estimated_usd": estimated_usd,
        "required_terms": list(case["required_terms"]),
        "forbidden_terms": list(case["forbidden_terms"]),
        "prompt": case["prompt"],
        "answer_contract": {
            "format": "concise operational answer with evidence, route decision, accounting, and stop conditions",
            "must_include": (
                "route decision",
                "evidence required",
                "accounting/cost note",
                "authority boundary",
                "next action",
            ),
        },
    }


def build_packet() -> dict[str, Any]:
    models = [_model_row(entry) for entry in model_catalog_entries()]
    prompts = [_prompt_row(case, model) for model in models for case in BENCHMARK_CASES]
    local_models = [
        row for row in models if row["provider_surface"] == "local-dgx-spark"
    ]
    cloud_prompts = [
        row for row in prompts if row["provider_surface"] != "local-dgx-spark"
    ]
    return {
        "schema": SCHEMA,
        "generated_at": int(time.time()),
        "dry_run_only": True,
        "model_calls_executed": 0,
        "owner": "uplink",
        "purpose": (
            "Run one large planner/offline benchmark packet across catalog LLMs, "
            "including future production DGX Spark local lanes, then feed promotion "
            "decisions back into planner routing."
        ),
        "summary": {
            "model_count": len(models),
            "case_count": len(BENCHMARK_CASES),
            "prompt_count": len(prompts),
            "local_dgx_spark_model_count": len(local_models),
            "personal_account_case_count": sum(
                1
                for case in BENCHMARK_CASES
                if case["account_scope"] in {"personal", "both"}
            ),
            "work_account_case_count": sum(
                1
                for case in BENCHMARK_CASES
                if case["account_scope"] in {"work", "both"}
            ),
            "estimated_cloud_run_cost_usd": round(
                sum(float(row["estimated_usd"]) for row in cloud_prompts), 6
            ),
            "local_marginal_token_cost_usd": 0.0,
        },
        "future_dgx_spark_run": {
            "target": "production DGX Spark",
            "status": "future_access_expected",
            "local_route_ids": [row["route_id"] for row in local_models],
            "promotion_gate": PROMOTION_POLICY,
        },
        "models": models,
        "cases": list(BENCHMARK_CASES),
        "prompts": prompts,
        "promotion_policy": PROMOTION_POLICY,
    }


def answer_template(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "norman.planner-llm-benchmark-answers.v1",
        "packet_schema": packet["schema"],
        "packet_generated_at": packet["generated_at"],
        "run_id": "fill-me",
        "runner": "uplink",
        "environment": {
            "host": "fill-me",
            "account_scope": "personal|work|both",
            "runtime_health_artifact": "path-or-url",
        },
        "answers": [
            {
                "prompt_id": prompt["prompt_id"],
                "case_id": prompt["case_id"],
                "candidate_id": prompt["candidate_id"],
                "answer": "",
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "latency_ms": 0,
                "estimated_usd": prompt["estimated_usd"],
                "runtime_health_status": "",
                "verifier_acceptance": "",
            }
            for prompt in packet["prompts"]
        ],
    }


def render_markdown(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    lines = [
        "# Planner LLM Benchmark Packet",
        "",
        f"- Owner: `{packet['owner']}`",
        f"- Dry run only: `{str(packet['dry_run_only']).lower()}`",
        f"- Model calls executed: `{packet['model_calls_executed']}`",
        f"- Models: `{summary['model_count']}`",
        f"- Cases: `{summary['case_count']}`",
        f"- Prompt rows: `{summary['prompt_count']}`",
        f"- Local DGX Spark models: `{summary['local_dgx_spark_model_count']}`",
        f"- Estimated cloud run cost: `${summary['estimated_cloud_run_cost_usd']:.6f}`",
        f"- Local marginal token cost: `${summary['local_marginal_token_cost_usd']:.6f}`",
        "",
        "## Promotion Rule",
        "",
        packet["promotion_policy"]["planner_consumption_rule"],
        "",
        "## Cases",
        "",
        "| Case | Account | Family | Required terms | Forbidden terms |",
        "| --- | --- | --- | --- | --- |",
    ]
    for case in packet["cases"]:
        lines.append(
            "| {case_id} | {account} | {family} | {required} | {forbidden} |".format(
                case_id=case["case_id"],
                account=case["account_scope"],
                family=case["family"],
                required=", ".join(case["required_terms"]),
                forbidden=", ".join(case["forbidden_terms"]),
            )
        )
    lines.extend(
        [
            "",
            "## Model Roster",
            "",
            "| Candidate | Surface | Tier | Cost basis |",
            "| --- | --- | --- | --- |",
        ]
    )
    for model in packet["models"]:
        lines.append(
            "| {route} | {surface} | {tier} | {basis} |".format(
                route=model["route_id"],
                surface=model["provider_surface"],
                tier=model["capability_tier"],
                basis=model["accounting"]["cost_basis"],
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--prompts-jsonl", type=Path, default=DEFAULT_PROMPTS_JSONL)
    parser.add_argument(
        "--answers-template-json",
        type=Path,
        default=DEFAULT_ANSWERS_TEMPLATE_JSON,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = build_packet()
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(packet, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(render_markdown(packet), encoding="utf-8")
    write_jsonl(args.prompts_jsonl, packet["prompts"])
    args.answers_template_json.parent.mkdir(parents=True, exist_ok=True)
    args.answers_template_json.write_text(
        json.dumps(answer_template(packet), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema": packet["schema"],
                "output_json": str(args.output_json),
                "output_md": str(args.output_md),
                "prompts_jsonl": str(args.prompts_jsonl),
                "answers_template_json": str(args.answers_template_json),
                "summary": packet["summary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
