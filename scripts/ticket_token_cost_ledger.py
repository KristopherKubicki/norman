#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


DEFAULT_LEDGER_JSONL = Path("/tmp/norman_tui_benchmarks/ticket_token_cost_ledger.jsonl")
DEFAULT_CHARGE_STATUS = "not_invoice_reconciled"
DEFAULT_ESTIMATE_LABEL = "estimated USD; not invoice-reconciled"

OPENAI_DIRECT_PRICING_USD_PER_1M = {
    "gpt-5.5": {"input": 5.00, "cached_input": 0.50, "output": 30.00},
    "gpt-5.4": {"input": 2.50, "cached_input": 0.25, "output": 15.00},
    "gpt-5.4-mini": {"input": 0.75, "cached_input": 0.075, "output": 4.50},
    "gpt-5.4-nano": {"input": 0.20, "cached_input": 0.02, "output": 1.25},
}

BEDROCK_US_EAST_2_PRICING_USD_PER_1M = {
    "openai.gpt-5.5": {"input": 5.50, "cached_input": 0.55, "output": 33.00},
    "openai.gpt-5.4": {"input": 2.75, "cached_input": 0.275, "output": 16.50},
}

PRICE_BASIS_SOURCES = {
    "auto": "selected per usage row from model/runtime hints",
    "none": "local or unpriced deterministic work",
    "openai-direct-standard": "https://openai.com/api/pricing/",
    "openai-direct-flex": "https://openai.com/api/pricing/",
    "bedrock-us-east-2": "https://aws.amazon.com/bedrock/pricing/",
}


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _clean_str(value: Any) -> str:
    return str(value or "").strip()


def _safe_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _record_id(record: dict[str, Any]) -> str:
    payload = {
        "ticket_id": record.get("ticket", {}).get("id"),
        "generated_at": record.get("generated_at"),
        "source": record.get("source"),
        "usage": record.get("usage"),
        "cost": record.get("cost"),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"ttc_{digest[:20]}"


def normalize_direct_model(model: str) -> str:
    clean = _clean_str(model)
    if clean.startswith("openai."):
        return clean.removeprefix("openai.")
    return clean


def infer_price_basis(runtime: str, model: str, service_tier: str = "") -> str:
    clean_model = _clean_str(model)
    clean_tier = _clean_str(service_tier).lower()
    if not clean_model or clean_model == "none":
        return "none"
    if clean_model in BEDROCK_US_EAST_2_PRICING_USD_PER_1M:
        return "bedrock-us-east-2"
    if normalize_direct_model(clean_model) in OPENAI_DIRECT_PRICING_USD_PER_1M:
        return (
            "openai-direct-flex" if clean_tier == "flex" else "openai-direct-standard"
        )
    if _clean_str(runtime).lower() in {"local", "none"}:
        return "none"
    return "none"


def pricing_for(model: str, price_basis: str) -> dict[str, float] | None:
    if price_basis == "none":
        return None
    if price_basis in {"openai-direct-standard", "openai-direct-flex"}:
        pricing = OPENAI_DIRECT_PRICING_USD_PER_1M.get(normalize_direct_model(model))
        if pricing is None:
            return None
        if price_basis == "openai-direct-flex":
            return {
                "input": pricing["input"] * 0.5,
                "cached_input": pricing["cached_input"] * 0.5,
                "output": pricing["output"] * 0.5,
            }
        return dict(pricing)
    if price_basis == "bedrock-us-east-2":
        return BEDROCK_US_EAST_2_PRICING_USD_PER_1M.get(model)
    return None


def estimate_usage_usd(
    *,
    model: str,
    price_basis: str,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
) -> tuple[float | None, bool]:
    if price_basis == "none":
        return 0.0, True
    pricing = pricing_for(model, price_basis)
    if pricing is None:
        return None, False
    cached_tokens = max(0, min(input_tokens, cached_input_tokens))
    uncached_input_tokens = max(0, input_tokens - cached_tokens)
    estimated = (
        uncached_input_tokens / 1_000_000 * pricing["input"]
        + cached_tokens / 1_000_000 * pricing["cached_input"]
        + output_tokens / 1_000_000 * pricing["output"]
    )
    return round(estimated, 6), True


def build_record(
    *,
    ticket_id: str,
    actor: str = "",
    thread_id: str = "",
    source_kind: str = "manual",
    source_ref: str = "",
    architecture_mode: str = "unknown",
    runtime: str = "",
    model: str = "",
    service_tier: str = "",
    price_basis: str = "auto",
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_output_tokens: int = 0,
    total_tokens: int = 0,
    usage_event_count: int = 0,
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    generated_at: int | None = None,
) -> dict[str, Any]:
    clean_ticket_id = _clean_str(ticket_id)
    if not clean_ticket_id:
        raise ValueError("ticket_id is required")
    input_count = max(0, _coerce_int(input_tokens))
    cached_count = max(0, _coerce_int(cached_input_tokens))
    output_count = max(0, _coerce_int(output_tokens))
    reasoning_count = max(0, _coerce_int(reasoning_output_tokens))
    billable_output_count = output_count + reasoning_count
    total_count = max(0, _coerce_int(total_tokens))
    if total_count == 0:
        total_count = input_count + output_count + reasoning_count
    selected_basis = (
        infer_price_basis(runtime, model, service_tier)
        if price_basis == "auto"
        else _clean_str(price_basis)
    )
    estimated_usd, cost_known = estimate_usage_usd(
        model=model,
        price_basis=selected_basis,
        input_tokens=input_count,
        cached_input_tokens=cached_count,
        output_tokens=billable_output_count,
    )
    record = {
        "schema": "norman.ticket-token-cost-record.v1",
        "generated_at": int(generated_at if generated_at is not None else time.time()),
        "ticket": {"id": clean_ticket_id},
        "source": {
            "kind": _clean_str(source_kind),
            "ref": _clean_str(source_ref),
            "thread_id": _clean_str(thread_id),
            "actor": _clean_str(actor),
        },
        "architecture": {"mode": _clean_str(architecture_mode) or "unknown"},
        "usage": {
            "runtime": _clean_str(runtime),
            "model": _clean_str(model),
            "service_tier": _clean_str(service_tier),
            "input_tokens": input_count,
            "cached_input_tokens": cached_count,
            "output_tokens": output_count,
            "reasoning_output_tokens": reasoning_count,
            "billable_output_tokens": billable_output_count,
            "total_tokens": total_count,
            "usage_event_count": max(0, _coerce_int(usage_event_count)),
        },
        "billing": {
            "estimate_label": DEFAULT_ESTIMATE_LABEL,
            "price_basis": selected_basis,
            "price_source": PRICE_BASIS_SOURCES.get(selected_basis, ""),
            "charge_ledger_kind": "api_rate_card_estimate"
            if selected_basis != "none"
            else "local_token_estimate",
            "charge_display_unit": "usd_equivalent"
            if selected_basis != "none"
            else "tokens",
            "charge_status": DEFAULT_CHARGE_STATUS,
            "cost_known": cost_known,
        },
        "cost": {"estimated_usd": estimated_usd},
        "notes": _clean_str(notes),
        "metadata": metadata or {},
    }
    record["id"] = _record_id(record)
    return record


def append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        if isinstance(data, dict):
            records.append(data)
    return records


def summarize_records(
    records: list[dict[str, Any]], ticket_id: str = ""
) -> dict[str, Any]:
    filtered = [
        record
        for record in records
        if not ticket_id or record.get("ticket", {}).get("id") == ticket_id
    ]
    estimated_usd_values = [
        float(record.get("cost", {}).get("estimated_usd") or 0.0)
        for record in filtered
        if record.get("cost", {}).get("estimated_usd") is not None
    ]
    return {
        "schema": "norman.ticket-token-cost-summary.v1",
        "generated_at": int(time.time()),
        "ticket_id": ticket_id,
        "records": len(filtered),
        "usage_event_count": sum(
            _coerce_int(record.get("usage", {}).get("usage_event_count"))
            for record in filtered
        ),
        "input_tokens": sum(
            _coerce_int(record.get("usage", {}).get("input_tokens"))
            for record in filtered
        ),
        "cached_input_tokens": sum(
            _coerce_int(record.get("usage", {}).get("cached_input_tokens"))
            for record in filtered
        ),
        "output_tokens": sum(
            _coerce_int(record.get("usage", {}).get("output_tokens"))
            for record in filtered
        ),
        "reasoning_output_tokens": sum(
            _coerce_int(record.get("usage", {}).get("reasoning_output_tokens"))
            for record in filtered
        ),
        "total_tokens": sum(
            _coerce_int(record.get("usage", {}).get("total_tokens"))
            for record in filtered
        ),
        "estimated_usd": round(sum(estimated_usd_values), 6),
        "charge_status": DEFAULT_CHARGE_STATUS,
        "estimate_label": DEFAULT_ESTIMATE_LABEL,
    }


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def load_usage_events(
    db_path: Path, *, thread_id: str = "", since_ts: int = 0
) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        columns = _table_columns(conn, "usage_events")
        if not columns:
            return []
        desired = [
            "thread_id",
            "started_at",
            "runtime",
            "model",
            "service_tier",
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
            "total_tokens",
            "payload_json",
        ]
        selected = [column for column in desired if column in columns]
        query = f"SELECT {', '.join(selected)} FROM usage_events WHERE 1=1"
        params: list[Any] = []
        if thread_id and "thread_id" in columns:
            query += " AND thread_id = ?"
            params.append(thread_id)
        if since_ts and "started_at" in columns:
            query += " AND started_at >= ?"
            params.append(since_ts)
        if "started_at" in columns:
            query += " ORDER BY started_at"
        rows = list(conn.execute(query, params))
    finally:
        conn.close()
    events: list[dict[str, Any]] = []
    for row in rows:
        payload = (
            _safe_json(row["payload_json"]) if "payload_json" in row.keys() else {}
        )
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        events.append(
            {
                "thread_id": _clean_str(row["thread_id"])
                if "thread_id" in row.keys()
                else "",
                "runtime": _clean_str(row["runtime"])
                if "runtime" in row.keys()
                else "",
                "model": _clean_str(row["model"]) if "model" in row.keys() else "",
                "service_tier": _clean_str(row["service_tier"])
                if "service_tier" in row.keys()
                else "",
                "input_tokens": _coerce_int(
                    row["input_tokens"] if "input_tokens" in row.keys() else 0
                )
                or _coerce_int(usage.get("input_tokens")),
                "cached_input_tokens": _coerce_int(
                    row["cached_input_tokens"]
                    if "cached_input_tokens" in row.keys()
                    else 0
                )
                or _coerce_int(usage.get("cached_input_tokens")),
                "output_tokens": _coerce_int(
                    row["output_tokens"] if "output_tokens" in row.keys() else 0
                )
                or _coerce_int(usage.get("output_tokens")),
                "reasoning_output_tokens": _coerce_int(
                    row["reasoning_output_tokens"]
                    if "reasoning_output_tokens" in row.keys()
                    else 0
                )
                or _coerce_int(usage.get("reasoning_output_tokens")),
                "total_tokens": _coerce_int(
                    row["total_tokens"] if "total_tokens" in row.keys() else 0
                )
                or _coerce_int(usage.get("total_tokens")),
            }
        )
    return events


def build_record_from_usage_events(
    *,
    ticket_id: str,
    events: list[dict[str, Any]],
    actor: str = "",
    source_ref: str = "",
    thread_id: str = "",
    architecture_mode: str = "unknown",
    price_basis: str = "auto",
    notes: str = "",
) -> dict[str, Any]:
    if not events:
        return build_record(
            ticket_id=ticket_id,
            actor=actor,
            thread_id=thread_id,
            source_kind="usage_db",
            source_ref=source_ref,
            architecture_mode=architecture_mode,
            runtime="none",
            model="none",
            price_basis="none",
            notes=notes or "No usage_events rows matched this ticket/thread.",
            metadata={"usage_event_count": 0},
        )
    runtimes = {
        _clean_str(event.get("runtime")) for event in events if event.get("runtime")
    }
    models = {_clean_str(event.get("model")) for event in events if event.get("model")}
    service_tiers = {
        _clean_str(event.get("service_tier"))
        for event in events
        if event.get("service_tier")
    }
    total_input = sum(_coerce_int(event.get("input_tokens")) for event in events)
    total_cached = sum(
        _coerce_int(event.get("cached_input_tokens")) for event in events
    )
    total_output = sum(_coerce_int(event.get("output_tokens")) for event in events)
    total_reasoning = sum(
        _coerce_int(event.get("reasoning_output_tokens")) for event in events
    )
    total_tokens = sum(_coerce_int(event.get("total_tokens")) for event in events)
    if total_tokens == 0:
        total_tokens = total_input + total_output + total_reasoning
    row_costs: list[float] = []
    cost_known = True
    row_bases: set[str] = set()
    for event in events:
        row_basis = (
            infer_price_basis(
                _clean_str(event.get("runtime")),
                _clean_str(event.get("model")),
                _clean_str(event.get("service_tier")),
            )
            if price_basis == "auto"
            else price_basis
        )
        row_bases.add(row_basis)
        row_cost, row_known = estimate_usage_usd(
            model=_clean_str(event.get("model")),
            price_basis=row_basis,
            input_tokens=_coerce_int(event.get("input_tokens")),
            cached_input_tokens=_coerce_int(event.get("cached_input_tokens")),
            output_tokens=_coerce_int(event.get("output_tokens")),
        )
        if not row_known:
            cost_known = False
        if row_cost is not None:
            row_costs.append(row_cost)
    record = build_record(
        ticket_id=ticket_id,
        actor=actor,
        thread_id=thread_id or _clean_str(events[0].get("thread_id")),
        source_kind="usage_db",
        source_ref=source_ref,
        architecture_mode=architecture_mode,
        runtime=next(iter(runtimes)) if len(runtimes) == 1 else "mixed",
        model=next(iter(models)) if len(models) == 1 else "mixed",
        service_tier=next(iter(service_tiers)) if len(service_tiers) == 1 else "mixed",
        price_basis="none" if row_bases == {"none"} else "auto",
        input_tokens=total_input,
        cached_input_tokens=total_cached,
        output_tokens=total_output,
        reasoning_output_tokens=total_reasoning,
        total_tokens=total_tokens,
        usage_event_count=len(events),
        notes=notes,
        metadata={
            "row_price_bases": sorted(row_bases),
            "runtimes": sorted(runtimes),
            "models": sorted(models),
            "service_tiers": sorted(service_tiers),
        },
    )
    record["billing"]["price_basis"] = (
        next(iter(row_bases)) if len(row_bases) == 1 else "mixed"
    )
    record["billing"]["price_source"] = (
        PRICE_BASIS_SOURCES.get(next(iter(row_bases)), "")
        if len(row_bases) == 1
        else "mixed"
    )
    if row_bases == {"none"}:
        record["billing"]["charge_ledger_kind"] = "local_token_estimate"
        record["billing"]["charge_display_unit"] = "tokens"
    else:
        record["billing"]["charge_ledger_kind"] = "api_rate_card_estimate"
        record["billing"]["charge_display_unit"] = "usd_equivalent"
    record["billing"]["cost_known"] = cost_known
    record["cost"]["estimated_usd"] = round(sum(row_costs), 6) if cost_known else None
    record["id"] = _record_id(record)
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record internal ticket-level token usage and estimated USD."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--ticket-id", required=True)
    record_parser.add_argument("--actor", default="")
    record_parser.add_argument("--thread-id", default="")
    record_parser.add_argument("--source-kind", default="manual")
    record_parser.add_argument("--source-ref", default="")
    record_parser.add_argument("--architecture-mode", default="unknown")
    record_parser.add_argument("--runtime", default="")
    record_parser.add_argument("--model", default="")
    record_parser.add_argument("--service-tier", default="")
    record_parser.add_argument(
        "--price-basis",
        choices=sorted(PRICE_BASIS_SOURCES),
        default="auto",
    )
    record_parser.add_argument("--input-tokens", type=int, default=0)
    record_parser.add_argument("--cached-input-tokens", type=int, default=0)
    record_parser.add_argument("--output-tokens", type=int, default=0)
    record_parser.add_argument("--reasoning-output-tokens", type=int, default=0)
    record_parser.add_argument("--total-tokens", type=int, default=0)
    record_parser.add_argument("--usage-event-count", type=int, default=0)
    record_parser.add_argument("--notes", default="")
    record_parser.add_argument(
        "--ledger-jsonl", type=Path, default=DEFAULT_LEDGER_JSONL
    )
    record_parser.add_argument("--print-json", action="store_true")

    usage_parser = subparsers.add_parser("from-usage-db")
    usage_parser.add_argument("--ticket-id", required=True)
    usage_parser.add_argument("--db-path", type=Path, required=True)
    usage_parser.add_argument("--thread-id", default="")
    usage_parser.add_argument("--since-ts", type=int, default=0)
    usage_parser.add_argument("--actor", default="")
    usage_parser.add_argument("--architecture-mode", default="unknown")
    usage_parser.add_argument(
        "--price-basis",
        choices=sorted(PRICE_BASIS_SOURCES),
        default="auto",
    )
    usage_parser.add_argument("--notes", default="")
    usage_parser.add_argument("--ledger-jsonl", type=Path, default=DEFAULT_LEDGER_JSONL)
    usage_parser.add_argument("--print-json", action="store_true")

    summary_parser = subparsers.add_parser("summarize")
    summary_parser.add_argument(
        "--ledger-jsonl", type=Path, default=DEFAULT_LEDGER_JSONL
    )
    summary_parser.add_argument("--ticket-id", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "record":
        record = build_record(
            ticket_id=args.ticket_id,
            actor=args.actor,
            thread_id=args.thread_id,
            source_kind=args.source_kind,
            source_ref=args.source_ref,
            architecture_mode=args.architecture_mode,
            runtime=args.runtime,
            model=args.model,
            service_tier=args.service_tier,
            price_basis=args.price_basis,
            input_tokens=args.input_tokens,
            cached_input_tokens=args.cached_input_tokens,
            output_tokens=args.output_tokens,
            reasoning_output_tokens=args.reasoning_output_tokens,
            total_tokens=args.total_tokens,
            usage_event_count=args.usage_event_count,
            notes=args.notes,
        )
        append_record(args.ledger_jsonl, record)
        print(
            json.dumps(
                record if args.print_json else summarize_records([record]),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "from-usage-db":
        events = load_usage_events(
            args.db_path,
            thread_id=args.thread_id,
            since_ts=args.since_ts,
        )
        record = build_record_from_usage_events(
            ticket_id=args.ticket_id,
            events=events,
            actor=args.actor,
            source_ref=str(args.db_path),
            thread_id=args.thread_id,
            architecture_mode=args.architecture_mode,
            price_basis=args.price_basis,
            notes=args.notes,
        )
        append_record(args.ledger_jsonl, record)
        print(
            json.dumps(
                record if args.print_json else summarize_records([record]),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "summarize":
        print(
            json.dumps(
                summarize_records(
                    load_records(args.ledger_jsonl), ticket_id=args.ticket_id
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
