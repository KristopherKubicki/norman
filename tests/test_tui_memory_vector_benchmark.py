from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_script(name: str):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    spec = importlib.util.spec_from_file_location(name, scripts_dir / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_vector_benchmark_separates_helpful_hits_and_known_gaps(
    tmp_path: Path,
) -> None:
    memory_tool = _load_script("tui_memory_tool")
    benchmark = _load_script("tui_memory_vector_benchmark")
    db = tmp_path / "tui_state.sqlite3"
    history = tmp_path / "history.jsonl"
    _write_jsonl(
        history,
        [
            {
                "thread_id": "thread-panelbot",
                "started_at": 1_780_000_000,
                "prompt": "Panelbot upload handoff failed.",
                "response": "The callback queue lost the attachment relay.",
            },
            {
                "thread_id": "thread-dashboard",
                "started_at": 1_780_000_100,
                "prompt": "Dashboard colors need review.",
                "response": "The dashboard color pass is unrelated.",
            },
        ],
    )
    cases = [
        {
            "id": "vector-only",
            "kind": "vector_helps",
            "query": "panelbot upload callback nonexistent-token",
            "expected_terms": ["panelbot", "upload"],
        },
        {
            "id": "hybrid",
            "kind": "hybrid_should_find",
            "query": "dashboard colors",
            "expected_terms": ["dashboard", "colors"],
        },
        {
            "id": "gap",
            "kind": "known_gap",
            "query": "not-a-real-memory-token",
            "expected_terms": ["not-a-real-memory-token"],
        },
    ]

    with memory_tool.connect(db) as conn:
        memory_tool.import_history_files(conn, [history])
        memory_tool.rebuild_memory_vectors(conn)

    report = benchmark.run_benchmark(db, cases, limit=3)
    markdown = benchmark.render_markdown(report)

    assert report["summary"]["cases"] == 3
    assert report["summary"]["passed"] == 3
    assert report["summary"]["failed"] == 0
    assert report["summary"]["vector_hits"] == 2
    assert report["summary"]["metadata_hits"] == 0
    assert report["summary"]["fts_hits"] == 1
    assert report["summary"]["hybrid_hits"] == 2
    assert report["summary"]["forbidden_hits"] == 0
    assert report["summary"]["avg_elapsed_ms"] >= 0
    assert report["summary"]["avg_hybrid_mrr"] > 0
    assert report["cases"][0]["fts_hit"] is False
    assert report["cases"][0]["vector_hit"] is True
    assert report["cases"][0]["vector_hit_row"]["thread_id"] == "thread-panelbot"
    assert report["cases"][0]["vector_first_hit_rank"] == 1
    assert report["cases"][0]["vector_mrr"] == 1.0
    assert report["cases"][0]["vector_precision_at_k"] > 0
    assert report["cases"][0]["elapsed_ms"] >= 0
    assert report["cases"][2]["hybrid_hit"] is False
    assert "TUI Memory Vector Benchmark" in markdown
    assert "Avg hybrid MRR" in markdown
    assert "vector-only" in markdown


def test_vector_benchmark_forbidden_terms_fail_case(tmp_path: Path) -> None:
    memory_tool = _load_script("tui_memory_tool")
    benchmark = _load_script("tui_memory_vector_benchmark")
    db = tmp_path / "tui_state.sqlite3"
    history = tmp_path / "history.jsonl"
    _write_jsonl(
        history,
        [
            {
                "thread_id": "thread-dashboard",
                "started_at": 1_780_000_100,
                "prompt": "Dashboard colors need review.",
                "response": "The dashboard color pass is unrelated.",
            },
        ],
    )

    with memory_tool.connect(db) as conn:
        memory_tool.import_history_files(conn, [history])
        memory_tool.rebuild_memory_vectors(conn)

    report = benchmark.run_benchmark(
        db,
        [
            {
                "id": "forbidden-dashboard",
                "kind": "hybrid_should_find",
                "query": "dashboard colors",
                "expected_terms": ["dashboard"],
                "forbidden_terms": ["dashboard"],
            }
        ],
        limit=3,
    )

    assert report["summary"]["cases"] == 1
    assert report["summary"]["failed"] == 1
    assert report["summary"]["forbidden_hits"] == 1
    assert report["cases"][0]["hybrid_hit"] is True
    assert report["cases"][0]["forbidden_hit"] is True
    assert report["cases"][0]["passed"] is False


def test_vector_benchmark_defaults_load_from_repo_case_file() -> None:
    benchmark = _load_script("tui_memory_vector_benchmark")

    cases = benchmark._load_cases(None)

    assert (
        benchmark.DEFAULT_CASES_PATH.name == "tui_memory_retrieval_benchmark_cases.json"
    )
    assert {case["id"] for case in cases} >= {
        "panelbot-upload-callback",
        "metadata-only-session-turn-id",
        "semantic-synonym-gap",
    }
