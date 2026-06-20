from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


def _load_ticket_ledger(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "ticket_token_cost_ledger",
        scripts_dir / "ticket_token_cost_ledger.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ticket_token_cost_ledger"] = module
    spec.loader.exec_module(module)
    return module


def test_build_record_estimates_flex_with_cached_input(monkeypatch) -> None:
    module = _load_ticket_ledger(monkeypatch)

    record = module.build_record(
        ticket_id="CP-123",
        actor="norman",
        architecture_mode="hybrid",
        runtime="openai",
        model="gpt-5.5",
        service_tier="flex",
        price_basis="auto",
        input_tokens=1000,
        cached_input_tokens=200,
        output_tokens=100,
        generated_at=123,
    )

    assert record["schema"] == "norman.ticket-token-cost-record.v1"
    assert record["ticket"]["id"] == "CP-123"
    assert record["billing"]["price_basis"] == "openai-direct-flex"
    assert record["billing"]["charge_status"] == "not_invoice_reconciled"
    assert (
        record["billing"]["estimate_label"] == "estimated USD; not invoice-reconciled"
    )
    assert record["usage"]["total_tokens"] == 1100
    assert record["cost"]["estimated_usd"] == 0.00355


def test_build_record_estimates_bedrock_openai_model(monkeypatch) -> None:
    module = _load_ticket_ledger(monkeypatch)

    record = module.build_record(
        ticket_id="GB-44",
        runtime="codex",
        model="openai.gpt-5.5",
        price_basis="auto",
        input_tokens=1000,
        output_tokens=100,
        generated_at=123,
    )

    assert record["billing"]["price_basis"] == "bedrock-us-east-2"
    assert (
        record["billing"]["price_source"] == "https://aws.amazon.com/bedrock/pricing/"
    )
    assert record["cost"]["estimated_usd"] == 0.0088


def test_direct_nano_rate_card_is_available_for_classifier_lanes(monkeypatch) -> None:
    module = _load_ticket_ledger(monkeypatch)

    record = module.build_record(
        ticket_id="CP-NANO",
        runtime="openai",
        model="gpt-5.4-nano",
        service_tier="flex",
        price_basis="auto",
        input_tokens=10_000,
        cached_input_tokens=2_000,
        output_tokens=1_000,
        generated_at=123,
    )

    assert record["billing"]["price_basis"] == "openai-direct-flex"
    assert record["cost"]["estimated_usd"] == 0.001445


def test_build_record_counts_reasoning_as_billable_output(monkeypatch) -> None:
    module = _load_ticket_ledger(monkeypatch)

    record = module.build_record(
        ticket_id="CP-456",
        runtime="codex",
        model="openai.gpt-5.5",
        price_basis="auto",
        input_tokens=1000,
        output_tokens=100,
        reasoning_output_tokens=50,
        generated_at=123,
    )

    assert record["usage"]["output_tokens"] == 100
    assert record["usage"]["reasoning_output_tokens"] == 50
    assert record["usage"]["billable_output_tokens"] == 150
    assert record["cost"]["estimated_usd"] == 0.01045


def test_build_record_from_usage_db_aggregates_thread_cost(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_ticket_ledger(monkeypatch)
    db_path = tmp_path / "tui_state.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE usage_events (
                thread_id TEXT,
                started_at INTEGER,
                runtime TEXT,
                model TEXT,
                service_tier TEXT,
                input_tokens INTEGER,
                cached_input_tokens INTEGER,
                output_tokens INTEGER,
                reasoning_output_tokens INTEGER,
                total_tokens INTEGER,
                payload_json TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO usage_events (
                thread_id, started_at, runtime, model, service_tier,
                input_tokens, cached_input_tokens, output_tokens,
                reasoning_output_tokens, total_tokens, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "thread-a",
                    10,
                    "openai",
                    "gpt-5.5",
                    "flex",
                    1000,
                    200,
                    100,
                    0,
                    1100,
                    "{}",
                ),
                (
                    "thread-a",
                    20,
                    "openai",
                    "gpt-5.4-mini",
                    "flex",
                    2000,
                    0,
                    400,
                    0,
                    2400,
                    "{}",
                ),
                (
                    "other-thread",
                    30,
                    "openai",
                    "gpt-5.5",
                    "flex",
                    10000,
                    0,
                    1000,
                    0,
                    11000,
                    "{}",
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    events = module.load_usage_events(db_path, thread_id="thread-a")
    record = module.build_record_from_usage_events(
        ticket_id="CP-456",
        events=events,
        actor="norman",
        source_ref=str(db_path),
        thread_id="thread-a",
        architecture_mode="hybrid",
    )

    assert record["usage"]["usage_event_count"] == 2
    assert record["usage"]["runtime"] == "openai"
    assert record["usage"]["model"] == "mixed"
    assert record["usage"]["input_tokens"] == 3000
    assert record["usage"]["output_tokens"] == 500
    assert record["usage"]["total_tokens"] == 3500
    assert record["billing"]["price_basis"] == "openai-direct-flex"
    assert record["billing"]["charge_ledger_kind"] == "api_rate_card_estimate"
    assert record["billing"]["charge_display_unit"] == "usd_equivalent"
    assert record["cost"]["estimated_usd"] == 0.0052


def test_cli_record_appends_jsonl_and_summarizes(tmp_path: Path, monkeypatch) -> None:
    module = _load_ticket_ledger(monkeypatch)
    ledger = tmp_path / "ticket_costs.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ticket_token_cost_ledger.py",
            "record",
            "--ticket-id",
            "CP-789",
            "--actor",
            "norman",
            "--runtime",
            "openai",
            "--model",
            "gpt-5.5",
            "--service-tier",
            "flex",
            "--price-basis",
            "auto",
            "--input-tokens",
            "1000",
            "--output-tokens",
            "100",
            "--ledger-jsonl",
            str(ledger),
        ],
    )

    assert module.main() == 0
    records = module.load_records(ledger)
    summary = module.summarize_records(records, ticket_id="CP-789")
    assert len(records) == 1
    assert records[0]["ticket"]["id"] == "CP-789"
    assert summary["records"] == 1
    assert summary["total_tokens"] == 1100
    assert summary["estimated_usd"] == 0.004
