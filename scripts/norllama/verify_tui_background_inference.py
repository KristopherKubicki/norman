#!/usr/bin/env python3
"""Verify Norman TUI background inference without recording user content."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_SCRIPT = REPO_ROOT / "scripts" / "norman_codex_web.py"


def load_switchboard() -> Any:
    spec = importlib.util.spec_from_file_location(
        "norman_tui_background_acceptance", WEB_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Norman switchboard")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def check_row(name: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(result.get("passed")),
        "status": str(result.get("status") or ""),
        "model": str(result.get("model") or ""),
        "candidate_policy": str(result.get("candidate_policy") or ""),
        "latency_ms": max(0, int(result.get("latency_ms") or 0)),
        "local_tokens": max(
            0, int(result.get("tokens") or result.get("local_tokens") or 0)
        ),
    }


def run_acceptance(module: Any) -> dict[str, Any]:
    resident_model = str(module.NORLLAMA_RESIDENT_MODEL or "")
    registry_version = str(
        module.NORLLAMA_RESIDENT_ROLE.get("registry_version") or ""
    )
    checks: list[dict[str, Any]] = []

    readiness = module.local_planner_preflight_readiness()
    checks.append(
        check_row(
            "planner_readiness",
            {
                **readiness,
                "passed": (
                    readiness.get("ready") is True
                    and readiness.get("model") == resident_model
                ),
            },
        )
    )

    planner = module.local_planner_preflight(
        {
            "schema": "norman.tui.context-preflight-request.v1",
            "agent": "acceptance",
            "session": "metadata-only",
            "host": "norman",
            "prompt_preview": "Summarize route risk and identify whether cloud review is needed.",
            "prompt_estimated_tokens": 64,
            "runtime": "codex",
            "model": "configured-cloud-model",
            "memory_refs": [
                {
                    "id": "acceptance-memory-1",
                    "prompt_preview": "Synthetic local support context.",
                    "response_preview": "Synthetic local support result.",
                }
            ],
            "memory_candidate_count": 1,
        }
    )
    checks.append(
        check_row(
            "planner_preflight",
            {
                **planner,
                "passed": (
                    planner.get("used") is True
                    and planner.get("status") == "ok"
                    and planner.get("model") == resident_model
                ),
            },
        )
    )

    verifier = module.local_planner_verifier(
        {
            "prompt_preview": "Verify synthetic archive recall.",
            "prompt_estimated_tokens": 64,
        },
        planner={
            **planner,
            "used": True,
            "status": "ok",
            "summary": "Synthetic recall requires a bounded verification.",
            "confidence": 0.4,
            "recall_status": "partial",
            "memory_ref_ids": ["acceptance-memory-1"],
        },
        memory_candidates=[
            {
                "id": "acceptance-memory-1",
                "prompt_preview": "Synthetic local support context.",
                "response_preview": "Synthetic local support result.",
            }
        ],
        selected_refs=[],
        memory_retrieval={"method": "acceptance", "candidate_count": 1},
    )
    checks.append(
        check_row(
            "planner_verifier",
            {
                **verifier,
                "passed": (
                    verifier.get("used") is True
                    and verifier.get("status") == "ok"
                    and verifier.get("model") == resident_model
                ),
            },
        )
    )

    recap_started = time.monotonic()
    recap, recap_model = module.working_recap_local_llm(
        {
            "last_started_at": int(time.time()) - 30,
            "running_runtime": "codex",
            "running_model": "configured-cloud-model",
            "turn_plan": {
                "understood_task": "Synthetic acceptance task.",
                "skill_labels": ["verification"],
                "plan_steps": ["Check readiness.", "Record metadata-only result."],
            },
            "live_turn": {
                "event_count": 2,
                "tool_started_count": 1,
                "tool_finished_count": 1,
                "last_tool_status": "tool-finished",
            },
        },
        {
            "turn_key": "acceptance",
            "status": "running",
            "headline": "Background inference acceptance",
            "now": "Checking the resident model.",
            "milestones": ["Planner readiness was requested."],
            "next": "Record a metadata-only receipt.",
        },
    )
    checks.append(
        check_row(
            "working_recap",
            {
                "passed": bool(recap) and recap_model == resident_model,
                "status": "ok" if recap else "failed",
                "model": recap_model,
                "latency_ms": int((time.monotonic() - recap_started) * 1000),
            },
        )
    )

    return {
        "schema": "norman.tui.background-inference-acceptance.v1",
        "recorded_at": int(time.time()),
        "registry_version": registry_version,
        "resident_model": resident_model,
        "checks": checks,
        "passed": bool(checks) and all(row["passed"] for row in checks),
        "content_recorded": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    receipt = run_acceptance(load_switchboard())
    text = json.dumps(receipt, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{text}\n", encoding="utf-8")
    print(text)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
