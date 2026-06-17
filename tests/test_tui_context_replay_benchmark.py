from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_replay_benchmark(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_context_replay_benchmark",
        scripts_dir / "tui_context_replay_benchmark.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_context_replay_benchmark"] = module
    spec.loader.exec_module(module)
    return module


def _sample_context_report() -> dict:
    return {
        "schema": "norman.tui.context-shadow-benchmark.v1",
        "summary": {
            "total_current_tokens": 23000,
            "total_packed_tokens": 7000,
            "total_saved_tokens": 16000,
            "saved_pct": 69.6,
        },
        "rows": [
            {
                "slug": "control-plane",
                "reachable": True,
                "state": "ok",
                "current_tokens": 16000,
                "packed_tokens": 4200,
                "saved_tokens": 11800,
                "saved_pct": 73.8,
                "saved_cost_label": "$0.006-$0.06",
                "state_db_enabled": True,
                "history_format": "jsonl_write_through_sqlite",
                "needs_retrieval_for_older_details": True,
                "requires_shadow_run_before_activation": True,
                "live_prompt_behavior_changed": False,
                "packed_sources": [
                    {
                        "label": "state card",
                        "tokens": 240,
                        "detail": "session summary",
                    },
                    {
                        "label": "recent turns",
                        "tokens": 2400,
                        "detail": "last 6 turns",
                    },
                    {
                        "label": "evidence refs",
                        "tokens": 728,
                        "detail": "18 older turn references",
                    },
                    {
                        "label": "tail digest",
                        "tokens": 400,
                        "detail": "pane/log digest",
                    },
                ],
                "excluded_sources": [
                    {
                        "label": "older turn bodies",
                        "tokens": 10000,
                        "detail": "replaced by 18 reference pointers",
                    },
                    {
                        "label": "raw pane/log tails",
                        "tokens": 900,
                        "detail": "replaced by tail digest",
                    },
                ],
            },
            {
                "slug": "panelbot",
                "reachable": True,
                "state": "running",
                "current_tokens": 7000,
                "packed_tokens": 2800,
                "saved_tokens": 4200,
                "saved_pct": 60.0,
                "state_db_enabled": True,
                "needs_retrieval_for_older_details": False,
                "requires_shadow_run_before_activation": True,
                "live_prompt_behavior_changed": False,
                "packed_sources": [
                    {"label": "state card", "tokens": 240},
                    {"label": "recent turns", "tokens": 1600},
                ],
                "excluded_sources": [],
            },
        ],
    }


def _sample_cases() -> list[dict]:
    return [
        {
            "id": "aggregate-status",
            "title": "Aggregate status",
            "tui": "norman",
            "required_facts": [{"id": "aggregate"}],
            "required_evidence": [{"id": "shadow-report"}],
            "answers": {},
        },
        {
            "id": "control-plane-runbooks",
            "title": "Control plane runbooks",
            "tui": "control_plane",
            "required_facts": [{"id": "runbook-proof"}],
            "required_evidence": [{"id": "sqlite-row"}],
            "wisdom_checks": [{"id": "do-not-overclaim"}],
            "answers": {"candidate": "Use DB rows, but shadow first."},
        },
        {
            "id": "missing-row",
            "title": "Missing row",
            "tui": "acast_tester",
            "context_tokens": {"baseline": 9000, "candidate": 5000},
            "answers": {"baseline": "old", "candidate": "new"},
        },
    ]


def test_build_report_surfaces_pointer_proof_and_shadow_gate(monkeypatch) -> None:
    module = _load_replay_benchmark(monkeypatch)

    report = module.build_report(_sample_context_report(), _sample_cases())

    assert report["schema"] == "norman.tui.context-replay-benchmark.v1"
    assert report["summary"]["reachable_rows"] == 2
    assert report["summary"]["db_enabled_rows"] == 2
    assert report["summary"]["rows_with_older_reference_proof"] == 1
    assert report["summary"]["shadow_run_ready"] is True
    assert report["summary"]["activation_safe"] is False

    control_plane = next(
        row for row in report["row_proofs"] if row["slug"] == "control-plane"
    )
    assert control_plane["verdict"] == "shadow-ready"
    assert (
        control_plane["older_turn_reference_proof"]["older_body_tokens_replaced"]
        == 10000
    )
    assert control_plane["older_turn_reference_proof"]["evidence_ref_tokens"] == 728
    assert control_plane["older_turn_reference_proof"]["saved_pct"] == 92.7


def test_case_replay_maps_aggregate_and_tui_aliases(monkeypatch) -> None:
    module = _load_replay_benchmark(monkeypatch)

    report = module.build_report(_sample_context_report(), _sample_cases())
    by_case = {case["case_id"]: case for case in report["case_replays"]}

    assert by_case["aggregate-status"]["matched_context_slug"] == "__aggregate__"
    assert by_case["aggregate-status"]["baseline_tokens"] == 23000
    assert by_case["aggregate-status"]["candidate_tokens"] == 7000
    assert by_case["control-plane-runbooks"]["matched_context_slug"] == "control-plane"
    assert by_case["control-plane-runbooks"]["baseline_tokens"] == 16000
    assert by_case["missing-row"]["has_context_row"] is False
    assert by_case["missing-row"]["baseline_tokens"] == 9000


def test_cli_writes_replay_report_and_answer_template(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_replay_benchmark(monkeypatch)
    context_path = tmp_path / "context.json"
    cases_path = tmp_path / "cases.json"
    output_json = tmp_path / "replay.json"
    output_md = tmp_path / "replay.md"
    answer_template = tmp_path / "answers.json"
    context_path.write_text(json.dumps(_sample_context_report()), encoding="utf-8")
    cases_path.write_text(
        json.dumps({"cases": _sample_cases()}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tui_context_replay_benchmark.py",
            "--context-report",
            str(context_path),
            "--cases",
            str(cases_path),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--output-answer-template",
            str(answer_template),
        ],
    )

    assert module.main() == 0
    report = json.loads(output_json.read_text(encoding="utf-8"))
    answers = json.loads(answer_template.read_text(encoding="utf-8"))

    assert report["summary"]["total_saved_tokens"] == 16000
    assert "TUI Context Replay Benchmark" in output_md.read_text(encoding="utf-8")
    assert answers["schema"] == "norman.tui.quality-shadow-answers.v1"
    assert len(answers["answers"]) == 6
