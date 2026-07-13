#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tui_kernel_acceptance as acceptance
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import tui_kernel_acceptance as acceptance  # type: ignore[no-redef]


DEFAULT_COHORT_TASKS = (
    "service_status_json",
    "supplied_text_summary",
    "log_triage",
    "readonly_code_explain",
)


@dataclass(frozen=True)
class CohortTask:
    name: str
    message_template: str
    description: str
    expected_task_kind: str = "chat"
    detail: int = 2
    job_budget: str = "3m"


def default_tasks() -> dict[str, CohortTask]:
    return {
        "service_status_json": CohortTask(
            name="service_status_json",
            description="Low-risk service status interpretation with JSON output.",
            message_template=(
                "Operator cohort local-first task. Do not use tools. Use local routing "
                "if eligible. Given service statuses api=healthy, billing=unhealthy "
                "timeout, cache=healthy, identify the unhealthy service. Return one "
                "compact JSON object with keys task, unhealthy_service, evidence, "
                "and nonce. Use nonce value {nonce}."
            ),
        ),
        "supplied_text_summary": CohortTask(
            name="supplied_text_summary",
            description="Summarization of supplied text only.",
            message_template=(
                "Operator cohort local-first task. Do not use tools or web. Summarize "
                "this supplied text in two concise bullets and include nonce {nonce}. "
                "Text: The local-first release path requires exact job ownership, "
                "visible TUI delivery, observed Spark worker proof, and zero hidden "
                "cloud fallback before production-default rollout."
            ),
        ),
        "log_triage": CohortTask(
            name="log_triage",
            description="Read-only log triage from supplied evidence.",
            message_template=(
                "Operator cohort local-first task. Do not use tools. Triage these "
                "log lines and return JSON with keys likely_issue, evidence, severity, "
                "and nonce={nonce}. Logs: 10:01 api ok; 10:02 billing timeout after "
                "5000ms; 10:03 cache ok; 10:04 billing retry timeout."
            ),
        ),
        "readonly_code_explain": CohortTask(
            name="readonly_code_explain",
            description="Read-only code explanation of a supplied snippet.",
            message_template=(
                "Operator cohort local-first task. Do not use tools or edit files. "
                "Explain what this Python function returns in one sentence and include "
                "nonce {nonce}: def pick(statuses): return [name for name, state in "
                "statuses.items() if state != 'healthy']"
            ),
        ),
    }


def split_names(raw: str, *, default: tuple[str, ...]) -> list[str]:
    return acceptance.split_names(raw, default=default)


def select_tasks(raw: str) -> list[CohortTask]:
    tasks = default_tasks()
    names = split_names(raw, default=DEFAULT_COHORT_TASKS)
    unknown = [name for name in names if name not in tasks]
    if unknown:
        raise ValueError("Unknown cohort task(s): %s" % ", ".join(sorted(unknown)))
    return [tasks[name] for name in names]


def cohort_scenario(task: CohortTask) -> acceptance.AcceptanceScenario:
    return acceptance.AcceptanceScenario(
        name=task.name,
        message_template=task.message_template,
        expected_template="{nonce}",
        description=task.description,
        runtime="auto",
        model="",
        route_lock=False,
        detail=task.detail,
        job_budget=task.job_budget,
        expected_task_kind=task.expected_task_kind,
        min_local_tokens=1,
        require_kernel_owned=True,
        require_local_first_on_target=True,
        require_norllama_tokens=True,
        require_worker_attribution=True,
        require_exact_ask_job_id=True,
        min_spark_evidence_count=1,
    )


def build_matrix(
    targets: list[acceptance.TuiTarget],
    tasks: list[CohortTask],
    *,
    run_id: str,
    turn_limit: int,
) -> list[tuple[acceptance.TuiTarget, acceptance.ScenarioRun]]:
    matrix: list[tuple[acceptance.TuiTarget, acceptance.ScenarioRun]] = []
    for target in targets:
        for task in tasks:
            if turn_limit and len(matrix) >= turn_limit:
                return matrix
            scenario = cohort_scenario(task)
            matrix.append(
                (
                    target,
                    acceptance.materialize_scenario(scenario, target, run_id=run_id),
                )
            )
    return matrix


def _dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value or {}, dict) else {}


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def result_local_tokens(result: dict[str, Any]) -> int:
    receipt = _dict(result.get("receipt"))
    return _int(receipt.get("goal_local_tokens") or receipt.get("local_tokens"))


def result_cloud_tokens(result: dict[str, Any]) -> int:
    receipt = _dict(result.get("receipt"))
    return _int(receipt.get("goal_cloud_tokens")) + _int(
        receipt.get("ledger_cloud_tokens")
    )


def receipt_passed(result: dict[str, Any], key: str) -> bool:
    receipt = _dict(result.get("receipt"))
    payload = _dict(receipt.get(key))
    if key == "receipt_audit":
        return acceptance._audit_passed(payload)
    if key == "completion_gate":
        return acceptance._completion_gate_passed(payload)
    return False


def build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for row in results if row.get("passed"))
    fully_local = [
        row
        for row in results
        if row.get("passed")
        and row.get("route_proof_passed")
        and row.get("visible_delivery_passed")
        and result_local_tokens(row) > 0
        and result_cloud_tokens(row) == 0
        and not _dict(row.get("receipt")).get("cloud_proxy")
    ]
    audit_passed = sum(1 for row in results if receipt_passed(row, "receipt_audit"))
    completion_passed = sum(
        1 for row in results if receipt_passed(row, "completion_gate")
    )
    observed_worker = sum(
        1
        for row in results
        if str(_dict(row.get("receipt")).get("observed_worker") or "").strip()
        and _dict(row.get("receipt")).get("observed_worker_source")
        == "gateway_response"
    )
    hidden_cloud = [
        row
        for row in results
        if result_cloud_tokens(row) > 0
        or bool(_dict(row.get("receipt")).get("cloud_proxy"))
    ]
    local_rate = (len(fully_local) / total) if total else 0.0
    audit_coverage = (audit_passed / total) if total else 0.0
    completion_coverage = (completion_passed / total) if total else 0.0
    worker_coverage = (observed_worker / total) if total else 0.0
    local_tokens = sum(result_local_tokens(row) for row in results)
    cloud_tokens = sum(result_cloud_tokens(row) for row in results)
    # This is a conservative release-cohort displacement floor: each fully local
    # eligible turn displaced a cloud LLM turn, but it is not a provider billing
    # baseline. Keep it separate from measured token avoidance.
    displaced_turns = len(fully_local)
    return {
        "total_turns": total,
        "passed_turns": passed,
        "fully_local_turns": len(fully_local),
        "fully_local_rate": round(local_rate, 4),
        "receipt_audit_coverage": round(audit_coverage, 4),
        "completion_gate_coverage": round(completion_coverage, 4),
        "observed_worker_coverage": round(worker_coverage, 4),
        "hidden_cloud_fallback_count": len(hidden_cloud),
        "local_tokens": local_tokens,
        "cloud_tokens": cloud_tokens,
        "cloud_llm_turns_displaced_floor": displaced_turns,
        "cloud_tokens_avoided_measured": 0,
        "cloud_tokens_avoided_measurement_available": False,
        "targets": sorted({str(row.get("target") or "") for row in results}),
        "tasks": sorted({str(row.get("scenario") or "") for row in results}),
        "workers": sorted(
            {
                str(_dict(row.get("receipt")).get("observed_worker") or "")
                for row in results
                if str(_dict(row.get("receipt")).get("observed_worker") or "").strip()
            }
        ),
    }


def gate_summary(summary: dict[str, Any], *, min_turns: int) -> dict[str, Any]:
    checks = {
        "min_turns": _int(summary.get("total_turns")) >= min_turns,
        "fully_local_rate": float(summary.get("fully_local_rate") or 0.0) >= 0.9,
        "receipt_audit_coverage": summary.get("receipt_audit_coverage") == 1.0,
        "completion_gate_coverage": summary.get("completion_gate_coverage") == 1.0,
        "observed_worker_coverage": summary.get("observed_worker_coverage") == 1.0,
        "hidden_cloud_fallback": _int(summary.get("hidden_cloud_fallback_count")) == 0,
        "cloud_tokens": _int(summary.get("cloud_tokens")) == 0,
        "cloud_llm_turns_displaced": _int(
            summary.get("cloud_llm_turns_displaced_floor")
        )
        > 0,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "missing": [key for key, value in checks.items() if not value],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run unlocked operator-like TUI local-first release cohort."
    )
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--targets", default="all")
    parser.add_argument("--tasks", default="default")
    parser.add_argument("--turn-limit", type=int, default=24)
    parser.add_argument("--min-turns", type=int, default=20)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument(
        "--runtime-api-base",
        default=acceptance.default_runtime_api_base(),
    )
    parser.add_argument("--runtime-token", default="")
    parser.add_argument("--poll-attempts", type=int, default=120)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--ask-timeout", type=float, default=30.0)
    parser.add_argument("--status-timeout", type=float, default=15.0)
    parser.add_argument("--ssh-timeout", type=float, default=600.0)
    parser.add_argument("--post-scenario-settle", type=float, default=2.0)
    parser.add_argument("--allow-local-db-fallback", action="store_true")
    parser.add_argument("--output-json", default="")
    return parser


def print_report(
    summary: dict[str, Any], gate: dict[str, Any], results: list[dict[str, Any]]
) -> None:
    print(
        "TUI operator cohort: %s/%s passed, fully-local rate %.1f%%"
        % (
            summary.get("passed_turns"),
            summary.get("total_turns"),
            float(summary.get("fully_local_rate") or 0.0) * 100.0,
        )
    )
    for row in results:
        receipt = _dict(row.get("receipt"))
        marker = "PASS" if row.get("passed") else "FAIL"
        print(
            "%s %-11s %-24s job=%s model=%s worker=%s local=%s cloud=%s"
            % (
                marker,
                row.get("target"),
                row.get("scenario"),
                row.get("job_id") or "-",
                receipt.get("selected_model") or "-",
                receipt.get("observed_worker") or "-",
                result_local_tokens(row),
                result_cloud_tokens(row),
            )
        )
        for failure in row.get("failures") or []:
            print("  - %s" % failure)
    print("Gate: %s" % ("PASS" if gate.get("passed") else "FAIL"))
    for missing in gate.get("missing") or []:
        print("  - %s" % missing)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        targets = acceptance.select_targets(args.targets)
        tasks = select_tasks(args.tasks)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    run_id = str(args.run_id or uuid.uuid4().hex[:10]).strip()
    matrix = build_matrix(
        targets,
        tasks,
        run_id=run_id,
        turn_limit=max(0, int(args.turn_limit or 0)),
    )
    if not args.live:
        print("Dry run. Add --live to send prompts.")
        for target, run in matrix:
            transport = "ssh:%s" % target.ssh_target if target.ssh_target else "local"
            print("%-11s %-24s %s %s" % (target.name, run.name, transport, run.nonce))
        return 0

    repo_root = Path(args.repo_root)
    runtime_api_base = str(args.runtime_api_base or "").strip()
    runtime_token = str(args.runtime_token or "").strip()
    if runtime_token:
        runtime_token_meta = {
            "runtime_token_source": "cli",
            "runtime_token_secret_name": "",
        }
    else:
        runtime_token, runtime_token_meta = (
            acceptance.resolve_console_runtime_token_with_source()
        )
    runtime_api_required = acceptance.acceptance_requires_runtime_api(targets)
    local_db_fallback_authorized = (
        acceptance.acceptance_allows_authoritative_local_db_fallback(
            targets=targets,
            repo_root=repo_root,
            allow_local_db_fallback=bool(args.allow_local_db_fallback),
        )
    )
    if (
        runtime_api_required
        and (not runtime_api_base or not runtime_token)
        and not local_db_fallback_authorized
    ):
        print(
            "operator cohort requires runtime API proof or Norman DB fallback",
            file=sys.stderr,
        )
        return 2

    results: list[dict[str, Any]] = []
    for index, (target, run) in enumerate(matrix, start=1):
        print(
            "Running %s/%s %s:%s" % (index, len(matrix), target.name, run.name),
            flush=True,
        )
        probe = acceptance.run_tui_probe(
            target,
            run,
            poll_attempts=args.poll_attempts,
            poll_interval=args.poll_interval,
            ask_timeout=args.ask_timeout,
            status_timeout=args.status_timeout,
            ssh_timeout=args.ssh_timeout,
        )
        job_id = acceptance.job_id_from_probe(probe)
        if not job_id:
            receipt = {"available": False, "error": "missing job id"}
        elif runtime_api_base and runtime_token:
            receipt = acceptance.receipt_from_norman_api_poll(
                job_id,
                api_base=runtime_api_base,
                token=runtime_token,
                timeout=args.status_timeout,
                poll_attempts=args.poll_attempts,
                poll_interval=args.poll_interval,
                accept_provable_running=False,
            )
            if not receipt.get("available") and (
                local_db_fallback_authorized or not runtime_api_required
            ):
                db_receipt = acceptance.receipt_from_norman_db_poll(
                    job_id,
                    repo_root=repo_root,
                    poll_attempts=args.poll_attempts,
                    poll_interval=args.poll_interval,
                    accept_provable_running=False,
                )
                if db_receipt.get("available"):
                    receipt = db_receipt
        elif local_db_fallback_authorized or not runtime_api_required:
            receipt = acceptance.receipt_from_norman_db_poll(
                job_id,
                repo_root=repo_root,
                poll_attempts=args.poll_attempts,
                poll_interval=args.poll_interval,
                accept_provable_running=False,
            )
        else:
            receipt = {
                "available": False,
                "error": "runtime API proof unavailable",
            }
        if job_id and receipt.get("available") and receipt.get("job_status") == "done":
            visible = acceptance.poll_visible_delivery(
                target,
                run,
                job_id=job_id,
                poll_attempts=args.poll_attempts,
                poll_interval=args.poll_interval,
                status_timeout=args.status_timeout,
                ssh_timeout=args.ssh_timeout,
            )
            probe["visible_delivery_poll"] = visible
            if isinstance(visible.get("status"), dict) and visible.get("status"):
                probe["status"] = visible["status"]
                probe["status_http_status"] = visible.get(
                    "status_http_status", probe.get("status_http_status", 0)
                )
        _passed, _failures, proof = acceptance.validate_acceptance(
            target, run, probe, receipt
        )
        proof["traffic_class"] = "operator_like_release_cohort"
        proof["synthetic"] = False
        results.append(proof)
        print(
            "%s %s:%s job=%s"
            % (
                "PASS" if proof.get("passed") else "FAIL",
                target.name,
                run.name,
                proof.get("job_id") or "-",
            ),
            flush=True,
        )
        if index < len(matrix) and float(args.post_scenario_settle or 0.0) > 0:
            time.sleep(float(args.post_scenario_settle))

    summary = build_summary(results)
    gate = gate_summary(summary, min_turns=max(1, int(args.min_turns or 1)))
    report = {
        "schema": "norman.tui-operator-local-first-cohort.v1",
        "run_id": run_id,
        "generated_at": int(time.time()),
        "hostname": (socket.gethostname() or "").strip(),
        "traffic_class": "operator_like_release_cohort",
        "benchmark": False,
        "acceptance": False,
        "route_locked_turns": 0,
        "shadow": False,
        "dry_run": False,
        "runtime_api": {
            "base": runtime_api_base,
            "token_available": bool(runtime_token),
            **runtime_token_meta,
        },
        "local_db_fallback": {
            "authorized": bool(local_db_fallback_authorized),
            "requested": bool(args.allow_local_db_fallback),
        },
        "summary": summary,
        "gate": gate,
        "passed": bool(gate.get("passed")),
        "results": results,
    }
    print_report(summary, gate, results)
    if args.output_json:
        Path(args.output_json).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
