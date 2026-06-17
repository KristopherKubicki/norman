from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_memory_tool(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_memory_tool",
        scripts_dir / "tui_memory_tool.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_memory_tool"] = module
    spec.loader.exec_module(module)
    return module


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_import_search_and_stats_are_idempotent(tmp_path: Path, monkeypatch) -> None:
    module = _load_memory_tool(monkeypatch)
    db = tmp_path / "tui_state.sqlite3"
    history = tmp_path / "history.jsonl"
    usage = tmp_path / "usage.jsonl"
    _write_jsonl(
        history,
        [
            {
                "thread_id": "thread-a",
                "started_at": 1_780_000_000,
                "finished_at": 1_780_000_120,
                "runtime": "codex",
                "model": "gpt-5.5",
                "prompt": "Review the confluence runbook for stage 7.",
                "response": "Stage 7 runbook evidence is ready.",
                "usage": {"total_tokens": 1200},
            },
            {
                "thread_id": "thread-b",
                "started_at": 1_780_003_600,
                "finished_at": 1_780_003_700,
                "runtime": "codex",
                "model": "gpt-5.5",
                "prompt": "Check panelbot upload failure.",
                "response": "Panelbot needs attachment feedback.",
                "usage": {"total_tokens": 800},
            },
        ],
    )
    _write_jsonl(
        usage,
        [
            {
                "thread_id": "thread-a",
                "started_at": 1_780_000_000,
                "finished_at": 1_780_000_120,
                "runtime": "codex",
                "model": "gpt-5.5",
                "input_tokens": 1000,
                "cached_input_tokens": 100,
                "output_tokens": 200,
                "total_tokens": 1200,
                "success": True,
                "charge_ledger_kind": "chatgpt_codex_credit_estimate",
                "charge_display_unit": "credits",
                "charge_status": "not_invoice_reconciled",
            }
        ],
    )

    with module.connect(db) as conn:
        first = module.import_history_files(conn, [history])
        second = module.import_history_files(conn, [history])
        module.import_usage_files(conn, [usage])
        result = module.search_turns(conn, query="stage runbook", limit=5)
        stats = module.stats(conn)
        usage_row = conn.execute(
            "SELECT charge_ledger_kind, charge_display_unit, charge_status "
            "FROM usage_events"
        ).fetchone()

    assert first["rows_imported"] == 2
    assert second["rows_imported"] == 2
    assert len(result["rows"]) == 1
    assert result["rows"][0]["thread_id"] == "thread-a"
    assert stats["turns"]["turns"] == 2
    assert stats["usage"]["usage_events"] == 1
    assert stats["usage_effective"]["events"] == 1
    assert stats["usage_effective"]["total_tokens"] == 1200
    assert stats["fts_enabled"] in {True, False}
    assert tuple(usage_row) == (
        "chatgpt_codex_credit_estimate",
        "credits",
        "not_invoice_reconciled",
    )


def test_discover_import_and_time_series(tmp_path: Path, monkeypatch) -> None:
    module = _load_memory_tool(monkeypatch)
    db = tmp_path / "tui_state.sqlite3"
    state_dir = tmp_path / "web-bridge"
    _write_jsonl(
        state_dir / "history.jsonl",
        [
            {
                "thread_id": "thread-a",
                "started_at": 1_780_000_000,
                "finished_at": 1_780_000_120,
                "prompt": "Control plane confluence pass.",
                "response": "Runbook shipped.",
                "usage": {"total_tokens": 100},
            }
        ],
    )
    _write_jsonl(
        state_dir / "recovery_20260601T000000Z" / "history.jsonl",
        [
            {
                "thread_id": "thread-recovery",
                "started_at": 1_780_086_400,
                "finished_at": 1_780_086_520,
                "prompt": "Recovered gold book work.",
                "response": "Recovery imported.",
                "usage": {"total_tokens": 200},
            }
        ],
    )
    _write_jsonl(
        state_dir / "usage-ledger.jsonl",
        [
            {
                "thread_id": "thread-a",
                "started_at": 1_780_000_000,
                "total_tokens": 100,
                "input_tokens": 80,
                "output_tokens": 20,
                "success": True,
            },
            {
                "thread_id": "thread-recovery",
                "started_at": 1_780_086_400,
                "total_tokens": 200,
                "input_tokens": 150,
                "output_tokens": 50,
                "success": True,
            },
        ],
    )

    with module.connect(db) as conn:
        history_paths = module.discover_history_files(state_dir)
        usage_paths = module.discover_usage_files(state_dir)
        module.import_history_files(conn, history_paths)
        module.import_usage_files(conn, usage_paths)
        series = module.time_series(conn, bucket="day")

    assert len(history_paths) == 2
    assert len(usage_paths) == 1
    assert sum(row.get("turns", 0) for row in series["rows"]) == 2
    assert sum(row.get("total_tokens", 0) for row in series["rows"]) == 300


def test_cli_search_prints_markdown(tmp_path: Path, monkeypatch, capsys) -> None:
    module = _load_memory_tool(monkeypatch)
    db = tmp_path / "tui_state.sqlite3"
    history = tmp_path / "history.jsonl"
    _write_jsonl(
        history,
        [
            {
                "thread_id": "thread-a",
                "started_at": 1_780_000_000,
                "prompt": "Find market sizing survey notes.",
                "response": "Survey Monte Carlo context found.",
            }
        ],
    )
    with module.connect(db) as conn:
        module.import_history_files(conn, [history])

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tui_memory_tool.py",
            "--db",
            str(db),
            "search",
            "market survey",
            "--print-md",
        ],
    )

    assert module.main() == 0
    output = capsys.readouterr().out
    assert "TUI Memory Search" in output
    assert "market sizing" in output


def test_usage_audit_derives_effective_cumulative_deltas(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_memory_tool(monkeypatch)
    db = tmp_path / "tui_state.sqlite3"
    usage = tmp_path / "usage-ledger.jsonl"
    _write_jsonl(
        usage,
        [
            {
                "thread_id": "bedrock-thread",
                "started_at": 1_780_000_000,
                "finished_at": 1_780_000_030,
                "runtime": "codex",
                "model": "gpt-5.5",
                "service_tier": "default",
                "input_tokens": 34_950_604,
                "cached_input_tokens": 22_393_100,
                "output_tokens": 113_528,
                "total_tokens": 35_064_132,
                "success": True,
            },
            {
                "thread_id": "bedrock-thread",
                "started_at": 1_780_000_060,
                "finished_at": 1_780_000_090,
                "runtime": "codex",
                "model": "gpt-5.5",
                "service_tier": "default",
                "input_tokens": 36_741_404,
                "cached_input_tokens": 23_241_990,
                "output_tokens": 114_588,
                "total_tokens": 36_855_992,
                "success": True,
            },
        ],
    )

    with module.connect(db) as conn:
        module.import_usage_files(conn, [usage])
        audit = module.usage_audit(conn, since_ts=1_780_000_000)
        file_audit = module.usage_audit_from_files([usage], since_ts=1_780_000_000)
        stats = module.stats(conn)

    assert audit["source"] == "state_db"
    assert file_audit["source"] == "usage_files"
    assert file_audit["rows_seen"] == 2
    assert file_audit["effective"]["total_tokens"] == 1_791_860
    assert audit["raw"]["total_tokens"] == 71_920_124
    assert audit["effective"]["total_tokens"] == 1_791_860
    assert audit["window"]["total_tokens"] == 1_791_860
    assert audit["meter_modes"] == {
        "cumulative_baseline": 1,
        "cumulative_delta": 1,
    }
    assert audit["charge_ledger_kinds"] == {
        "chatgpt_codex_credit_estimate": 2,
    }
    assert audit["charge_display_units"] == {"credits": 2}
    assert audit["charge_statuses"] == {"not_invoice_reconciled": 2}
    assert audit["zero_effective_events"] == 1
    assert stats["usage"]["total_tokens"] == 71_920_124
    assert stats["usage_effective"]["total_tokens"] == 1_791_860


def test_cli_usage_audit_prints_markdown(tmp_path: Path, monkeypatch, capsys) -> None:
    module = _load_memory_tool(monkeypatch)
    db = tmp_path / "tui_state.sqlite3"
    usage = tmp_path / "usage.jsonl"
    _write_jsonl(
        usage,
        [
            {
                "thread_id": "thread-a",
                "started_at": 1_780_000_000,
                "finished_at": 1_780_000_010,
                "input_tokens": 80,
                "output_tokens": 20,
                "total_tokens": 100,
                "success": True,
                "billing_unit": "norman:thread-a",
            }
        ],
    )
    with module.connect(db) as conn:
        module.import_usage_files(conn, [usage])

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tui_memory_tool.py",
            "--db",
            str(db),
            "usage-audit",
            "--since",
            "1779999999",
            "--print-md",
        ],
    )

    assert module.main() == 0
    output = capsys.readouterr().out
    assert "TUI Usage Audit" in output
    assert "Source: `state_db`" in output
    assert "Effective total tokens: `100`" in output
    assert "Charge ledger kinds:" in output
    assert "chatgpt_codex_credit_estimate" in output
    assert "Charge display units:" in output
    assert "credits" in output
    assert "Card charge: `no`" in output
    assert (
        "Display basis: `personal Codex credits; API-dollar values are comparison only`"
        in output
    )
    assert "norman:thread-a" in output
