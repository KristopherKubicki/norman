from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_quality_benchmark(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_quality_benchmark", scripts_dir / "tui_quality_benchmark.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_quality_benchmark"] = module
    spec.loader.exec_module(module)
    return module


def test_seed_context_case_scores_candidate_above_baseline(monkeypatch) -> None:
    module = _load_quality_benchmark(monkeypatch)
    cases = module.load_cases(module.DEFAULT_CASES)
    case = next(item for item in cases if item["id"] == "context-pack-proof-status")

    report = module.score_case(case)
    by_label = {score.label: score for score in report.answer_scores}

    assert by_label["candidate"].score > by_label["baseline"].score
    assert by_label["candidate"].score >= 90
    assert by_label["candidate"].fact_recall == 1.0
    assert by_label["candidate"].evidence_recall == 1.0
    assert by_label["candidate"].trap_free == 1.0
    assert by_label["baseline"].hallucination_trap_hits == 2
    assert report.context_saved_pct == 70.9


def test_report_summary_and_markdown_surface_review_flags(monkeypatch) -> None:
    module = _load_quality_benchmark(monkeypatch)
    cases = module.load_cases(module.DEFAULT_CASES)

    report = module.build_report(cases)
    markdown = module.render_markdown(report)

    assert report["summary"]["case_count"] >= 4
    assert (
        report["summary"]["candidate_avg_score"]
        > report["summary"]["baseline_avg_score"]
    )
    assert report["summary"]["deep_reasoning_case_count"] >= 4
    assert report["summary"]["compared_case_count"] >= 3
    assert report["summary"]["candidate_dominates_baseline_case_count"] >= 3
    assert report["summary"]["candidate_regression_case_count"] == 0
    assert report["summary"]["contract_scored_answer_count"] >= 6
    assert "context-pack-proof-status" in markdown
    assert "Candidate reasoning depth" in markdown
    assert "Candidate vs Baseline" in markdown
    assert "Candidate vs baseline average delta" in markdown
    assert "Trap hits: all-tuis-ten, invoice-grade-overclaim" in markdown


def test_deep_reasoning_case_penalizes_shallow_baseline(monkeypatch) -> None:
    module = _load_quality_benchmark(monkeypatch)
    cases = module.load_cases(module.DEFAULT_CASES)
    case = next(
        item for item in cases if item["id"] == "approval-boundary-route-selection"
    )

    report = module.score_case(case)
    by_label = {score.label: score for score in report.answer_scores}

    assert by_label["candidate"].reasoning_depth == 1.0
    assert by_label["candidate"].completeness == 1.0
    assert by_label["baseline"].reasoning_depth < 1.0
    assert by_label["baseline"].fact_recall < 1.0
    assert by_label["baseline"].contract_score < 1.0
    assert by_label["candidate"].score > by_label["baseline"].score
    assert report.candidate_dominates_baseline is True
    assert report.candidate_regressions == []


def test_cli_writes_json_and_markdown_outputs(tmp_path: Path, monkeypatch) -> None:
    module = _load_quality_benchmark(monkeypatch)
    output_json = tmp_path / "quality.json"
    output_md = tmp_path / "quality.md"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tui_quality_benchmark.py",
            "--cases",
            str(module.DEFAULT_CASES),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
    )

    assert module.main() == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["schema"] == "norman.tui.quality-benchmark-report.v1"
    assert "TUI Quality Benchmark" in output_md.read_text(encoding="utf-8")


def test_answer_overlay_replaces_seed_answers_and_adds_run_metadata(
    monkeypatch,
) -> None:
    module = _load_quality_benchmark(monkeypatch)
    cases = module.load_cases(module.DEFAULT_CASES)
    overlay = module.load_answer_overlay(module.DEFAULT_ANSWERS_EXAMPLE)

    overlaid = module.apply_answer_overlay(cases, overlay)
    report = module.build_report(
        overlaid,
        run_metadata={"run_id": overlay["run_id"], "source": "example"},
    )
    markdown = module.render_markdown(report)

    assert report["run"]["run_id"] == "example-shadow-run"
    assert "## Run" in markdown
    assert "example-shadow-run" in markdown
    assert (
        report["summary"]["candidate_avg_score"]
        > report["summary"]["baseline_avg_score"]
    )
    assert report["summary"]["case_count"] == len(cases)
    assert report["summary"]["answer_count"] == len(overlay["answers"])


def test_require_pairs_reports_cases_missing_shadow_outputs(monkeypatch) -> None:
    module = _load_quality_benchmark(monkeypatch)
    cases = module.apply_answer_overlay(
        module.load_cases(module.DEFAULT_CASES),
        {
            "answers": [
                {
                    "case_id": "context-pack-proof-status",
                    "label": "baseline",
                    "answer": "Everything is fine.",
                }
            ]
        },
    )

    missing = module.missing_answer_pairs(cases)

    assert "context-pack-proof-status" in missing
    assert "guarded-rollout-status" not in missing


def test_cli_require_pairs_fails_for_incomplete_shadow_overlay(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_quality_benchmark(monkeypatch)
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            {
                "answers": [
                    {
                        "case_id": "context-pack-proof-status",
                        "label": "baseline",
                        "answer": "Everything is fine.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tui_quality_benchmark.py",
            "--answers",
            str(answers),
            "--require-pairs",
        ],
    )

    with pytest.raises(ValueError, match="missing baseline/candidate"):
        module.main()


def test_duplicate_overlay_pairs_are_rejected(tmp_path: Path, monkeypatch) -> None:
    module = _load_quality_benchmark(monkeypatch)
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            {
                "answers": [
                    {
                        "case_id": "context-pack-proof-status",
                        "label": "baseline",
                        "answer": "one",
                    },
                    {
                        "case_id": "context-pack-proof-status",
                        "label": "baseline",
                        "answer": "two",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate overlay answer"):
        module.load_answer_overlay(answers)


def test_deep_reasoning_case_requires_answer_contract(monkeypatch) -> None:
    module = _load_quality_benchmark(monkeypatch)

    with pytest.raises(
        ValueError, match="deep-reasoning case must define answer_contract"
    ):
        module.validate_cases(
            [
                {
                    "id": "broken-deep-case",
                    "tui": "norman",
                    "category": "decision-authority",
                    "requires_deep_reasoning": True,
                    "required_facts": [{"id": "fact", "all_terms": ["one"]}],
                    "required_evidence": [{"id": "evidence", "all_terms": ["two"]}],
                    "wisdom_checks": [{"id": "wisdom", "all_terms": ["three"]}],
                    "known_traps": [{"id": "trap", "forbidden_terms": ["four"]}],
                }
            ]
        )


def test_report_flags_candidate_regression_dimensions(monkeypatch) -> None:
    module = _load_quality_benchmark(monkeypatch)
    cases = [
        {
            "id": "regression-case",
            "title": "Regression case",
            "tui": "norman",
            "category": "regression",
            "required_facts": [{"id": "fact", "all_terms": ["anchor"]}],
            "answers": {
                "baseline": "anchor anchor because evidence decision next",
                "candidate": "because decision next",
            },
        }
    ]

    report = module.build_report(cases)
    case = report["cases"][0]

    assert report["summary"]["compared_case_count"] == 1
    assert report["summary"]["candidate_regression_case_count"] == 1
    assert "fact_recall" in report["summary"]["candidate_regressions_by_dimension"]
    assert case["candidate_dominates_baseline"] is False
    assert "fact_recall" in case["candidate_regressions"]
