#!/usr/bin/env python3
"""Score planner timing contracts against operator-expectation cases."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


SCHEMA = "norman.planner-time-contract-benchmark.v1"
POLICY_VERSION = "planner-time-contract.v1"
DEFAULT_OUTPUT_JSON = Path("tmp/planner_time_contract_benchmark.json")
DEFAULT_OUTPUT_MD = Path("tmp/planner_time_contract_benchmark.md")

QUICK_WORK_CLASSES = {"direct_answer", "quick_decision", "status", "approval_boundary"}
DONEISH_STATUSES = {"done", "checkpoint", "blocked"}
PROCEED_TERMS = (
    "proceed",
    "continue",
    "keep going",
    "keep working",
    "next concrete step",
)

DEFAULT_CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "quick-status-finishes-early-with-evidence",
        "prompt": "status?",
        "work_class": "status",
        "requested_target_seconds": 300,
        "elapsed_seconds": 2,
        "time_contract_present": True,
        "evidence_count": 1,
        "final_status": "done",
        "expected_violation_codes": [],
    },
    {
        "case_id": "long-work-empty-plan-returns-in-two-seconds",
        "prompt": "work on this for a couple hours and make real progress",
        "work_class": "long_work",
        "requested_target_seconds": 7200,
        "elapsed_seconds": 2,
        "time_contract_present": True,
        "evidence_count": 0,
        "final_status": "done",
        "expected_violation_codes": ["premature_return_without_evidence"],
    },
    {
        "case_id": "five-minute-task-runs-hours-without-checkpoint",
        "prompt": "this should be a five minute check",
        "work_class": "focused_slice",
        "requested_target_seconds": 300,
        "elapsed_seconds": 14400,
        "time_contract_present": True,
        "evidence_count": 3,
        "checkpoint_count": 0,
        "final_status": "checkpoint",
        "expected_violation_codes": ["overrun_without_checkpoint"],
    },
    {
        "case_id": "proceed-continues-from-checkpoint",
        "prompt": "Proceed from your last answer. Continue with the next concrete step.",
        "work_class": "proceed_resume",
        "requested_target_seconds": 600,
        "elapsed_seconds": 420,
        "time_contract_present": True,
        "evidence_count": 2,
        "checkpoint_available": True,
        "checkpoint_next_action_used": True,
        "final_status": "done",
        "expected_violation_codes": [],
    },
    {
        "case_id": "proceed-repeats-setup-instead-of-next-action",
        "prompt": "Proceed from your last answer. Continue with the next concrete step.",
        "work_class": "proceed_resume",
        "requested_target_seconds": 600,
        "elapsed_seconds": 10,
        "time_contract_present": True,
        "evidence_count": 0,
        "checkpoint_available": True,
        "checkpoint_next_action_used": False,
        "final_status": "done",
        "expected_violation_codes": ["proceed_did_not_use_checkpoint"],
    },
)


def _clean_str(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _job_budget_seconds(value: Any) -> int:
    raw = _clean_str(value).lower()
    if not raw:
        return 0
    try:
        if raw.endswith("m"):
            return int(float(raw[:-1]) * 60)
        if raw.endswith("h"):
            return int(float(raw[:-1]) * 3600)
        if raw.endswith("s"):
            return int(float(raw[:-1]))
        return int(float(raw))
    except ValueError:
        return 0


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _clean_str(value).lower() in {"1", "true", "yes", "on"}


def _is_proceed_prompt(prompt: str) -> bool:
    lower = prompt.lower()
    return any(term in lower for term in PROCEED_TERMS)


def _infer_work_class(prompt: str, requested_seconds: int) -> str:
    lower = prompt.lower()
    if _is_proceed_prompt(prompt):
        return "proceed_resume"
    if "status" in lower or "what's next" in lower or "whats next" in lower:
        return "status"
    if requested_seconds >= 3600:
        return "long_work"
    if requested_seconds <= 300:
        return "quick_decision"
    return "focused_slice"


def detected_violation_codes(case: dict[str, Any]) -> list[str]:
    requested = _int(case.get("requested_target_seconds"))
    elapsed = _int(case.get("elapsed_seconds"))
    evidence_count = _int(case.get("evidence_count"))
    checkpoint_count = _int(case.get("checkpoint_count"))
    work_class = _clean_str(case.get("work_class")).lower()
    final_status = _clean_str(case.get("final_status")).lower()
    prompt = _clean_str(case.get("prompt"))
    violations: list[str] = []

    if not _bool(case.get("time_contract_present")):
        violations.append("missing_time_contract")
    if (
        requested >= 900
        and elapsed <= 60
        and evidence_count == 0
        and work_class not in QUICK_WORK_CLASSES
        and final_status in DONEISH_STATUSES
    ):
        violations.append("premature_return_without_evidence")
    if requested > 0 and elapsed > max(requested * 2, requested + 900):
        if checkpoint_count <= 0:
            violations.append("overrun_without_checkpoint")
    if (
        _is_proceed_prompt(prompt)
        and _bool(case.get("checkpoint_available"))
        and not _bool(case.get("checkpoint_next_action_used"))
    ):
        violations.append("proceed_did_not_use_checkpoint")
    return violations


def score_case(case: dict[str, Any]) -> dict[str, Any]:
    policy_assertion = "expected_violation_codes" in case
    expected = sorted(str(code) for code in case.get("expected_violation_codes") or [])
    detected = sorted(detected_violation_codes(case))
    return {
        "case_id": _clean_str(case.get("case_id")),
        "source": _clean_str(case.get("source")) or "synthetic",
        "prompt": _clean_str(case.get("prompt")),
        "work_class": _clean_str(case.get("work_class")),
        "requested_target_seconds": _int(case.get("requested_target_seconds")),
        "elapsed_seconds": _int(case.get("elapsed_seconds")),
        "policy_assertion": policy_assertion,
        "expected_violation_codes": expected,
        "detected_violation_codes": detected,
        "pass": True if not policy_assertion else expected == detected,
    }


def load_history_cases(state_db: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    if not state_db.exists():
        return []
    conn = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, started_at, finished_at, job_budget, timeout_seconds,
                   prompt_preview, response_preview, prompt_chars, response_chars,
                   usage_total_tokens, success, payload_json
            FROM turns
            WHERE finished_at > started_at
            ORDER BY finished_at DESC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()

    cases: list[dict[str, Any]] = []
    for row in rows:
        prompt = _clean_str(row["prompt_preview"])
        response_preview = _clean_str(row["response_preview"])
        requested = _int(row["timeout_seconds"]) or _job_budget_seconds(
            row["job_budget"]
        )
        elapsed = max(0, _int(row["finished_at"]) - _int(row["started_at"]))
        final_status = "done" if _int(row["success"]) else "blocked"
        checkpoint_count = 1 if "checkpoint" in response_preview.lower() else 0
        if checkpoint_count:
            final_status = "checkpoint"
        evidence_count = sum(
            [
                1 if _int(row["response_chars"]) >= 240 else 0,
                1 if _int(row["usage_total_tokens"]) > 0 else 0,
                1 if response_preview else 0,
            ]
        )
        cases.append(
            {
                "case_id": f"history:{_clean_str(row['id'])[:12]}",
                "source": "history",
                "prompt": prompt,
                "work_class": _infer_work_class(prompt, requested),
                "requested_target_seconds": requested,
                "elapsed_seconds": elapsed,
                "time_contract_present": requested > 0,
                "evidence_count": evidence_count,
                "checkpoint_count": checkpoint_count,
                "checkpoint_available": False,
                "checkpoint_next_action_used": False,
                "final_status": final_status,
            }
        )
    return cases


def build_report(cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = [score_case(case) for case in cases or list(DEFAULT_CASES)]
    detected_counts: dict[str, int] = {}
    history_detected_counts: dict[str, int] = {}
    for row in rows:
        for code in row["detected_violation_codes"]:
            detected_counts[code] = detected_counts.get(code, 0) + 1
            if row["source"] == "history":
                history_detected_counts[code] = history_detected_counts.get(code, 0) + 1
    policy_rows = [row for row in rows if row["policy_assertion"]]
    fail_count = sum(1 for row in policy_rows if not row["pass"])
    return {
        "schema": SCHEMA,
        "policy_version": POLICY_VERSION,
        "generated_at": int(time.time()),
        "dry_run_only": True,
        "model_calls_executed": 0,
        "summary": {
            "case_count": len(rows),
            "policy_case_count": len(policy_rows),
            "history_observation_count": len(rows) - len(policy_rows),
            "policy_case_pass_count": len(policy_rows) - fail_count,
            "policy_case_fail_count": fail_count,
            "detected_violation_count": sum(detected_counts.values()),
            "detected_violation_counts": detected_counts,
            "history_violation_counts": history_detected_counts,
            "gate": "pass" if fail_count == 0 else "fail",
        },
        "rows": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Planner Time Contract Benchmark",
        "",
        f"- Policy: `{report['policy_version']}`",
        f"- Gate: `{summary['gate']}`",
        f"- Cases: `{summary['case_count']}`",
        f"- History observations: `{summary['history_observation_count']}`",
        f"- Policy case failures: `{summary['policy_case_fail_count']}`",
        f"- Detected violations: `{summary['detected_violation_count']}`",
        "",
        "| Case | Source | Pass | Expected | Detected |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in report["rows"]:
        lines.append(
            "| `{case_id}` | {source} | {passed} | `{expected}` | `{detected}` |".format(
                case_id=row["case_id"],
                source=row["source"],
                passed="yes" if row["pass"] else "no",
                expected=", ".join(row["expected_violation_codes"]) or "none",
                detected=", ".join(row["detected_violation_codes"]) or "none",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--include-history", action="store_true")
    parser.add_argument("--history-limit", type=int, default=50)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cases = list(DEFAULT_CASES)
    if args.include_history and args.state_db:
        cases.extend(load_history_cases(args.state_db, limit=args.history_limit))
    report = build_report(cases)
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
