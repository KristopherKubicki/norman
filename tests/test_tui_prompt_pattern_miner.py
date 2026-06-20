from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


def _load_module():
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "tui_prompt_pattern_miner.py"
    )
    spec = importlib.util.spec_from_file_location("tui_prompt_pattern_miner", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_prompt_pattern_miner"] = module
    spec.loader.exec_module(module)
    return module


def _write_turns_db(path: Path, rows: list[dict]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE turns (
                started_at INTEGER,
                prompt_preview TEXT,
                response_preview TEXT,
                error_preview TEXT,
                payload_json TEXT
            )
            """
        )
        for index, row in enumerate(rows, start=1):
            payload = {
                "prompt": row["prompt"],
                "response": row.get("response", "DONE"),
                "error": row.get("error", ""),
            }
            conn.execute(
                "INSERT INTO turns VALUES (?, ?, ?, ?, ?)",
                (
                    index,
                    row["prompt"][:120],
                    row.get("response", "")[:120],
                    row.get("error", "")[:120],
                    json.dumps(payload),
                ),
            )


def test_prompt_pattern_miner_classifies_operator_meta_patterns() -> None:
    module = _load_module()

    prompt = (
        "ok and on the memory, is there a way to make that more dynamic, "
        "or handle things better so we dont have bad cases? do we have more "
        "headroom? maybe?"
    )

    assert module.question_style(prompt) == "stacked_question"
    patterns = module.meta_patterns(prompt)
    assert "question_stack" in patterns
    assert "cost_pressure" in patterns
    assert "correction_or_refinement" in patterns
    assert "uncertainty_marker" in patterns
    assert (
        module.likely_next_move("other", "stacked_question", patterns)
        == "run_cost_or_route_policy_before_recommending"
    )


def test_prompt_pattern_miner_builds_template_rows(tmp_path: Path) -> None:
    module = _load_module()
    db_path = tmp_path / "state.sqlite3"
    _write_turns_db(
        db_path,
        [
            {
                "prompt": "Make it so. Do the concrete thing you just proposed.",
                "response": "Implemented it.\nDONE",
            },
            {
                "prompt": "Proceed from your last answer. Continue with the next concrete step.",
                "response": "Blocked: missing approval.\nBLOCKED",
            },
            {
                "prompt": "can you check are all the tuis using the dbs properly?",
                "response": "Checked it. Evidence follows.\nDONE",
            },
        ],
    )

    report = module.build_report(db_path)
    rows = {row["template"]: row for row in report["rows"]}

    assert report["summary"]["turn_count"] == 3
    assert rows["make_it_so"]["dominant_next_move"] == (
        "extract_prior_recommendation_then_execute_or_gate"
    )
    assert rows["proceed_from_last_answer"]["negative_or_checkpoint_pct"] == 100.0
    assert rows["can_you_check"]["dominant_route_hint"] == (
        "local_or_deterministic_preflight_first"
    )


def test_prompt_pattern_miner_cli_writes_reports(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    output_json = tmp_path / "patterns.json"
    output_md = tmp_path / "patterns.md"
    _write_turns_db(
        db_path,
        [
            {
                "prompt": "i thought we use the db now not jsonls?",
                "response": "Verified against SQLite.\nDONE",
            }
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/tui_prompt_pattern_miner.py",
            "--state-db",
            str(db_path),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
        check=True,
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    payload = json.loads(output_json.read_text())
    assert (
        payload["summary"]["meta_pattern_counts"]["memory_or_expectation_challenge"]
        == 1
    )
    assert "TUI Prompt Patterns" in output_md.read_text()
    assert "output_json" in result.stdout
