from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


def _load_benchmark(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_bedrock_shortstop_benchmark",
        scripts_dir / "tui_bedrock_shortstop_benchmark.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_bedrock_shortstop_benchmark"] = module
    spec.loader.exec_module(module)
    return module


def _create_state_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE turns (
                id TEXT PRIMARY KEY,
                thread_id TEXT,
                started_at INTEGER,
                finished_at INTEGER,
                runtime TEXT,
                model TEXT,
                speed TEXT,
                service_tier TEXT,
                success INTEGER,
                usage_total_tokens INTEGER,
                prompt_preview TEXT,
                response_preview TEXT,
                error_preview TEXT,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE usage_events (
                id TEXT PRIMARY KEY,
                thread_id TEXT,
                started_at INTEGER,
                finished_at INTEGER,
                runtime TEXT,
                model TEXT,
                speed TEXT,
                service_tier TEXT,
                success INTEGER,
                input_tokens INTEGER,
                cached_input_tokens INTEGER,
                output_tokens INTEGER,
                reasoning_output_tokens INTEGER,
                total_tokens INTEGER,
                usage_meter_mode TEXT,
                provider_yield_kind TEXT,
                provider_yield_reasons TEXT,
                provider_error_kind TEXT,
                provider_request_ids TEXT,
                provider_trace_ids TEXT,
                codex_returncode INTEGER,
                zero_token_provider_failure INTEGER,
                payload_json TEXT NOT NULL
            );
            """
        )
        rows = [
            (
                "short",
                "thread-a",
                100,
                105,
                "codex",
                "openai.gpt-5.5",
                "xhigh",
                "default",
                1,
                50039,
                "check the repo",
                "I'll inspect the repo and then run the checks.",
                "",
                {
                    "prompt": "check the repo",
                    "response": "I'll inspect the repo and then run the checks.",
                    "usage": {"total_tokens": 50039, "output_tokens": 39},
                },
            ),
            (
                "zero",
                "thread-b",
                200,
                219,
                "codex",
                "openai.gpt-5.5",
                "xhigh",
                "default",
                0,
                0,
                "canary",
                "",
                "stream disconnected before completion",
                {
                    "prompt": "canary",
                    "response": "",
                    "error": "stream disconnected before completion",
                },
            ),
            (
                "done",
                "thread-c",
                300,
                360,
                "codex",
                "openai.gpt-5.5",
                "xhigh",
                "default",
                1,
                25000,
                "summarize",
                "DONE. I inspected the repo and ran the checks.",
                "",
                {
                    "prompt": "summarize",
                    "response": "DONE. I inspected the repo and ran the checks.",
                    "usage": {"total_tokens": 25000, "output_tokens": 1200},
                },
            ),
            (
                "visible-low-yield",
                "thread-d",
                400,
                415,
                "codex",
                "gpt-5.5",
                "balanced",
                "flex",
                1,
                295648,
                "what improvements remain on the context sheet?",
                "Short answer.\n\nIt needs clearer status badges and better coverage.",
                "",
                {
                    "prompt": "what improvements remain on the context sheet?",
                    "response": "Short answer.\n\n"
                    + "It needs clearer status badges and better coverage. " * 25,
                    "usage": {
                        "input_tokens": 290573,
                        "cached_input_tokens": 217344,
                        "output_tokens": 5075,
                        "reasoning_output_tokens": 2167,
                        "total_tokens": 295648,
                    },
                },
            ),
        ]
        conn.executemany(
            """
            INSERT INTO turns(
                id, thread_id, started_at, finished_at, runtime, model, speed,
                service_tier, success, usage_total_tokens, prompt_preview,
                response_preview, error_preview, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [row[:-1] + (json.dumps(row[-1]),) for row in rows],
        )
        usage_rows = [
            (
                "usage-short",
                "thread-a",
                100,
                105,
                "codex",
                "openai.gpt-5.5",
                "xhigh",
                "default",
                1,
                50000,
                0,
                39,
                0,
                50039,
                "per_turn",
                "short_stop",
                '["final response promises future work"]',
                "",
                '["req-short"]',
                "[]",
                0,
                0,
                "{}",
            ),
            (
                "usage-zero",
                "thread-b",
                200,
                219,
                "codex",
                "openai.gpt-5.5",
                "xhigh",
                "default",
                0,
                0,
                0,
                0,
                0,
                0,
                "per_turn",
                "zero_transport",
                '["zero-token provider failure"]',
                "bedrock_stream_disconnected",
                '["req-zero"]',
                "[]",
                1,
                1,
                "{}",
            ),
            (
                "usage-done",
                "thread-c",
                300,
                360,
                "codex",
                "openai.gpt-5.5",
                "xhigh",
                "default",
                1,
                23800,
                0,
                1200,
                400,
                25000,
                "per_turn",
                "",
                "[]",
                "",
                "[]",
                "[]",
                0,
                0,
                "{}",
            ),
            (
                "usage-visible-low-yield",
                "thread-d",
                400,
                415,
                "codex",
                "gpt-5.5",
                "balanced",
                "flex",
                1,
                290573,
                217344,
                5075,
                2167,
                295648,
                "per_turn",
                "",
                "[]",
                "",
                "[]",
                "[]",
                0,
                0,
                "{}",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO usage_events(
                id, thread_id, started_at, finished_at, runtime, model, speed,
                service_tier, success, input_tokens, cached_input_tokens,
                output_tokens, reasoning_output_tokens, total_tokens,
                usage_meter_mode, provider_yield_kind, provider_yield_reasons,
                provider_error_kind, provider_request_ids,
                provider_trace_ids, codex_returncode,
                zero_token_provider_failure, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            usage_rows,
        )
        conn.commit()
    finally:
        conn.close()


def test_benchmark_classifies_short_stops_and_zero_failures(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_benchmark(monkeypatch)
    db_path = tmp_path / "tui_state.sqlite3"
    _create_state_db(db_path)

    records = module.load_tui_records(db_path, label="kpi", since_ts=0)
    report = module.summarize_records(records)

    assert report["schema"] == "norman.tui.bedrock-shortstop-benchmark.v1"
    assert report["summary"]["categories"] == {
        "low_yield": 1,
        "short_stop": 1,
        "useful_or_unclassified": 1,
        "zero_transport": 1,
    }
    kpi = report["summary"]["tuis"][0]
    assert kpi["short_stop_reasoning_zero"] == 1
    assert kpi["short_stop_with_request_ids"] == 1
    assert report["summary"]["mechanisms"]["future_work_promise"] == 1
    assert report["summary"]["mechanisms"]["provider_zero_transport"] == 1
    assert report["summary"]["mechanisms"]["thin_output"] == 1
    assert report["summary"]["mechanisms"]["zero_reasoning"] == 2
    assert (
        "Auto-continue" in report["summary"]["mechanism_hints"]["future_work_promise"]
    )
    short = next(row for row in report["rows"] if row["turn_id"] == "short")
    assert short["category"] == "short_stop"
    assert "final response promises future work" in short["reasons"]
    assert short["mechanisms"] == ["future_work_promise", "zero_reasoning"]
    low_yield = next(
        row for row in report["rows"] if row["turn_id"] == "visible-low-yield"
    )
    assert low_yield["category"] == "low_yield"
    assert "short visible response chars" in " ".join(low_yield["reasons"])
    assert "thin_output" in low_yield["mechanisms"]


def test_cli_writes_report(tmp_path: Path, monkeypatch) -> None:
    module = _load_benchmark(monkeypatch)
    db_path = tmp_path / "tui_state.sqlite3"
    output_json = tmp_path / "report.json"
    output_md = tmp_path / "report.md"
    _create_state_db(db_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tui_bedrock_shortstop_benchmark.py",
            "--db",
            f"kpi={db_path}",
            "--since-hours",
            "1000000",
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
    )

    assert module.main() == 0
    report = json.loads(output_json.read_text(encoding="utf-8"))

    assert report["run"]["databases"][0]["label"] == "kpi"
    assert report["summary"]["categories"]["short_stop"] == 1
    assert report["summary"]["categories"]["low_yield"] == 1
    markdown = output_md.read_text(encoding="utf-8")
    assert "TUI Bedrock Short-Stop Benchmark" in markdown
    assert "## Mechanisms" in markdown
    assert "future_work_promise" in markdown
