from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_shadow_benchmark(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_context_shadow_benchmark",
        scripts_dir / "tui_context_shadow_benchmark.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_context_shadow_benchmark"] = module
    spec.loader.exec_module(module)
    return module


def test_build_report_summarizes_live_status_preview(monkeypatch) -> None:
    module = _load_shadow_benchmark(monkeypatch)
    statuses = [
        {
            "_shadow_slug": "control-plane",
            "_shadow_url": "https://cp.kris.openbrand.com/api/status",
            "state": "ok",
            "context_pack_preview": {
                "state": "strong",
                "current": {
                    "tokens": 20000,
                    "sources": [{"label": "history", "tokens": 18000}],
                },
                "packed": {
                    "tokens": 5000,
                    "sources": [{"label": "recent turns", "tokens": 4200}],
                },
                "savings": {
                    "tokens": 15000,
                    "pct": 75.0,
                    "cost_range": {"label": "$0.01-$0.10"},
                },
                "storage": {
                    "state_db_enabled": True,
                    "history_format": "jsonl_write_through_sqlite",
                },
                "quality_gate": {
                    "needs_retrieval_for_older_details": True,
                    "requires_shadow_run_before_activation": True,
                    "live_prompt_behavior_changed": False,
                },
            },
        },
        {
            "_shadow_slug": "panelbot",
            "_shadow_error": "URLError: timeout",
        },
    ]

    report = module.build_report(statuses, source="fixture")
    markdown = module.render_markdown(report)
    template = module.build_answer_template(report)

    assert report["summary"]["sampled"] == 2
    assert report["summary"]["reachable"] == 1
    assert report["summary"]["total_current_tokens"] == 20000
    assert report["summary"]["total_packed_tokens"] == 5000
    assert report["summary"]["saved_pct"] == 75.0
    assert report["summary"]["db_enabled_rows"] == 1
    assert report["summary"]["shadow_required_rows"] == 1
    assert "control-plane" in markdown
    assert "URLError: timeout" in markdown
    assert template["answers"][0]["context_tokens"] == 20000
    assert template["answers"][1]["context_tokens"] == 5000


def test_load_status_source_accepts_prior_rows_shape(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_shadow_benchmark(monkeypatch)
    source = tmp_path / "sample.json"
    source.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "slug": "infra",
                        "reachable": True,
                        "state": "ok",
                        "current_tokens": 13121,
                        "packed_tokens": 4668,
                        "saved_tokens": 8453,
                        "saved_pct": 64.4,
                        "preview_state": "strong",
                        "quality_gate": {
                            "needs_retrieval_for_older_details": True,
                            "requires_shadow_run_before_activation": True,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    statuses = module.load_status_source(source)
    report = module.build_report(statuses, source=str(source))

    assert report["summary"]["reachable"] == 1
    assert report["rows"][0]["slug"] == "infra"
    assert report["rows"][0]["saved_tokens"] == 8453
    assert report["rows"][0]["needs_retrieval_for_older_details"] is True


def test_cli_writes_report_and_answer_template(tmp_path: Path, monkeypatch) -> None:
    module = _load_shadow_benchmark(monkeypatch)
    source = tmp_path / "sample.json"
    output_json = tmp_path / "shadow.json"
    output_md = tmp_path / "shadow.md"
    output_answers = tmp_path / "answers.json"
    source.write_text(
        json.dumps(
            [
                {
                    "slug": "infra",
                    "current_tokens": 10000,
                    "packed_tokens": 4000,
                    "saved_tokens": 6000,
                    "saved_pct": 60.0,
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tui_context_shadow_benchmark.py",
            "--source-json",
            str(source),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--output-answer-template",
            str(output_answers),
        ],
    )

    assert module.main() == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    answers = json.loads(output_answers.read_text(encoding="utf-8"))
    assert data["schema"] == "norman.tui.context-shadow-benchmark.v1"
    assert answers["schema"] == "norman.tui.quality-shadow-answers.v1"
    assert "TUI Context Shadow Benchmark" in output_md.read_text(encoding="utf-8")
