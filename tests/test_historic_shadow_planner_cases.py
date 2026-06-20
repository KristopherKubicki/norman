from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def _load_cases_module(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "historic_shadow_planner_cases",
        scripts_dir / "historic_shadow_planner_cases.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["historic_shadow_planner_cases"] = module
    spec.loader.exec_module(module)
    return module


def _sample_report() -> dict[str, Any]:
    return {
        "schema": "norman.work-session-runbook-miner.v1",
        "dry_run_only": True,
        "model_calls_executed": 0,
        "turn_count": 20,
        "candidate_count": 2,
        "summary": {"evidence_turn_count": 12},
        "rows": [
            {
                "pattern_id": "bbs_handoff_lifecycle",
                "label": "BBS handoff lifecycle",
                "domain": "bbs",
                "family": "coordination",
                "owner_tui": "switchboard/control-plane",
                "tenant_boundary": "cross-tenant coordination",
                "evidence_turn_count": 7,
                "thread_count": 3,
                "first_seen": "2026-06-13T00:00:00Z",
                "last_seen": "2026-06-14T01:00:00Z",
                "runbook_outputs": ["bbs-handoff-close-loop"],
                "skill_outputs": ["bbs-coordination"],
                "tool_outputs": ["scripts/bbs_task_lifecycle.py"],
                "deterministic_validators": ["actor/owner match", "ack note present"],
                "lower_model_role": "summarize state and propose close-loop action",
                "final_model_gate": "Bedrock GPT-5.4 xhigh only for ambiguous ownership",
                "live_authority": (
                    "ACK/fork/done/blocked writes require explicit role decision"
                ),
                "hybridization": "local ledger parser; cheap model drafts coordination note",
                "recommendation": "Use lower models before the authority gate.",
                "benchmark_cases_to_add": [
                    "observer must not ACK",
                    "owner ACK allowed",
                ],
                "scores": {
                    "comfort": "worker_only_until_gate",
                    "hybrid_value_score": 1.0,
                    "repeatability_score": 1.0,
                    "automation_safety_score": 0.7,
                },
                "evidence_samples": [{"prompt": "redacted historic evidence sample"}],
            },
            {
                "pattern_id": "runbook_contract_pack_audit",
                "label": "Runbook contract-pack audit",
                "domain": "runbook-governance",
                "family": "governance",
                "owner_tui": "control-plane",
                "tenant_boundary": "work runbooks stay work",
                "evidence_turn_count": 2,
                "thread_count": 1,
                "first_seen": "2026-06-12T00:00:00Z",
                "last_seen": "2026-06-12T01:00:00Z",
                "runbook_outputs": ["runbook-contract-pack"],
                "skill_outputs": ["runbook-pack-authoring"],
                "tool_outputs": ["scripts/runbook_contract_pack_audit.py"],
                "deterministic_validators": ["authority_gates present"],
                "lower_model_role": "extract evidence/action/authority fields",
                "final_model_gate": "Bedrock GPT-5.4 xhigh for tiering",
                "live_authority": "no live action; governance changes require review",
                "hybridization": "cheap extraction with deterministic schema audit",
                "recommendation": "Promote to runbook/skill candidate.",
                "benchmark_cases_to_add": ["missing authority gate"],
                "scores": {"comfort": "comfortable_shadow_lower_worker"},
            },
        ],
    }


def test_build_cases_derives_splits_gates_and_blocked_actions(monkeypatch) -> None:
    module = _load_cases_module(monkeypatch)

    manifest = module.build_cases(
        _sample_report(),
        max_patterns=2,
        cases_per_pattern=2,
        min_evidence=1,
        holdout_after="2026-06-14",
    )

    assert manifest["schema"] == "norman.historic-shadow-planner-cases.v1"
    assert manifest["summary"]["case_count"] == 3
    assert manifest["summary"]["split_counts"] == {"holdout": 2, "train": 1}
    assert manifest["source"]["model_calls_executed"] == 0

    by_id = {case["id"]: case for case in manifest["cases"]}
    bbs_case = by_id["historic-bbs_handoff_lifecycle-01-observer-must-not-ack"]
    assert bbs_case["split"] == "holdout"
    assert bbs_case["expected"]["authority_gate"] == "approval_required_before_mutation"
    assert bbs_case["expected"]["allow_live_mutation"] is False
    assert set(bbs_case["expected"]["blocked_actions"]) >= {
        "ack",
        "blocked",
        "done",
        "fork",
        "live mutation",
        "unapproved write",
    }
    assert "bbs-handoff-close-loop" in bbs_case["expected"]["required_terms"]

    audit_case = by_id["historic-runbook_contract_pack_audit-01-missing-authority-gate"]
    assert audit_case["split"] == "train"
    assert audit_case["expected"]["authority_gate"] == "read_only_shadow"
    assert audit_case["expected"]["allow_live_mutation"] is False


def test_cli_writes_manifest_and_markdown(tmp_path: Path, monkeypatch) -> None:
    module = _load_cases_module(monkeypatch)
    input_path = tmp_path / "miner.json"
    output_json = tmp_path / "cases.json"
    output_md = tmp_path / "cases.md"
    input_path.write_text(json.dumps(_sample_report()), encoding="utf-8")

    result = module.main(
        [
            "--input-json",
            str(input_path),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--max-patterns",
            "2",
            "--cases-per-pattern",
            "2",
            "--min-evidence",
            "1",
            "--holdout-after",
            "2026-06-14",
        ]
    )

    assert result == 0
    manifest = json.loads(output_json.read_text(encoding="utf-8"))
    markdown = output_md.read_text(encoding="utf-8")
    assert manifest["summary"]["case_count"] == 3
    assert manifest["summary"]["pattern_count"] == 2
    assert "| Case | Split | Domain | Gate | Runbook | Evidence |" in markdown
    assert "Source model calls: 0" in markdown
