#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_LIMIT = 20
USAGE_WINDOW_SECONDS = 24 * 60 * 60
USAGE_CUMULATIVE_DETECT_MIN_TOKENS = 1_000_000
USAGE_CUMULATIVE_BASELINE_MIN_TOKENS = 5_000_000
USAGE_AUDIT_GROUP_LIMIT = 12
SESSION_TEXT_LIMIT = 120_000
MEMORY_VECTOR_MODEL = "local-sparse-v1"
MEMORY_VECTOR_DIMENSION = 0
MEMORY_CHUNK_CHARS = 2400
MEMORY_CHUNK_OVERLAP = 240
MEMORY_VECTOR_MIN_TOKEN_LEN = 3
MEMORY_VECTOR_STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "this",
    "with",
    "you",
    "are",
    "was",
    "were",
    "have",
    "has",
    "had",
    "not",
    "but",
    "from",
    "into",
    "your",
    "our",
    "can",
    "should",
    "would",
    "could",
    "will",
    "just",
    "about",
    "what",
    "when",
    "where",
    "which",
    "then",
    "than",
}
MEMORY_REDACTED_SECRET = "[REDACTED:secret]"
MEMORY_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|API[_-]?KEY|"
    r"PRIVATE[_-]?KEY|CLIENT[_-]?SECRET|WEBHOOK[_-]?SECRET|ACCESS[_-]?KEY|"
    r"REFRESH[_-]?TOKEN|COOKIE|CSRF)[A-Z0-9_-]*\s*=\s*)([^\s'\"<>]+)",
    re.IGNORECASE,
)
MEMORY_SECRET_JSON_RE = re.compile(
    r"([\"']?[a-z0-9_.-]*(?:secret|token|password|passwd|credential|api[_-]?key|"
    r"private[_-]?key|client[_-]?secret|webhook[_-]?secret|access[_-]?key|"
    r"refresh[_-]?token|cookie|csrf)[a-z0-9_.-]*[\"']?\s*[:=]\s*[\"'])"
    r"([^\"'\s,}]+)([\"']?)",
    re.IGNORECASE,
)
MEMORY_BEARER_RE = re.compile(
    r"\b(Authorization\s*:\s*Bearer\s+|Bearer\s+)([A-Za-z0-9._~+/=-]{8,})",
    re.IGNORECASE,
)
MEMORY_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
MEMORY_AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")


def now_ts() -> int:
    return int(time.time())


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_runtime(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if clean in {"claude", "anthropic"}:
        return "claude"
    if clean in {"kimi", "moonshot"}:
        return "kimi"
    if clean in {"qwen", "dashscope", "alibaba"}:
        return "qwen"
    return clean or "codex"


def usage_charge_ledger_kind(entry: dict[str, Any]) -> str:
    explicit = str(entry.get("charge_ledger_kind") or "").strip().lower()
    if explicit:
        return explicit
    runtime = normalize_runtime(entry.get("runtime"))
    owner = str(entry.get("billing_owner") or "").strip().lower()
    group = str(entry.get("agent_group") or "").strip().lower()
    provider_surface = str(entry.get("provider_surface") or "").strip().lower()
    if runtime == "codex" and group != "work" and owner in {"", "kristopher"}:
        return "chatgpt_codex_credit_estimate"
    if runtime in {"claude", "kimi", "qwen"}:
        return "provider_invoice_estimate"
    if provider_surface == "aws-bedrock":
        return "provider_invoice_estimate"
    if provider_surface == "openai-direct":
        return "api_rate_card_estimate"
    return "local_token_estimate"


def usage_charge_display_unit(ledger_kind: str) -> str:
    if ledger_kind == "chatgpt_codex_credit_estimate":
        return "credits"
    if ledger_kind in {"api_rate_card_estimate", "provider_invoice_estimate"}:
        return "usd_equivalent"
    return "tokens"


def usage_charge_status(entry: dict[str, Any]) -> str:
    explicit = str(entry.get("charge_status") or "").strip().lower()
    return explicit or "not_invoice_reconciled"


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, default=str)


def _preview(text: Any, limit: int = 220) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "..."


def _parse_time(value: str | None) -> int | None:
    if not value:
        return None
    clean = value.strip()
    if not clean:
        return None
    if clean.isdigit():
        return int(clean)
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(clean)
    except ValueError as exc:
        raise ValueError(f"invalid time: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def state_db_id(kind: str, payload: dict[str, Any]) -> str:
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else payload
    material = json.dumps(
        {
            "kind": kind,
            "thread_id": payload.get("thread_id"),
            "started_at": payload.get("started_at"),
            "finished_at": payload.get("finished_at"),
            "prompt": str(payload.get("prompt") or "")[:512],
            "response": str(payload.get("response") or "")[:512],
            "error": str(payload.get("error") or payload.get("error_text") or "")[:512],
            "total_tokens": usage.get("total_tokens"),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _redact_memory_text(text: Any) -> tuple[str, int]:
    clean = str(text or "")
    redactions = 0

    clean, count = MEMORY_PRIVATE_KEY_RE.subn(MEMORY_REDACTED_SECRET, clean)
    redactions += count
    clean, count = MEMORY_AWS_ACCESS_KEY_RE.subn(MEMORY_REDACTED_SECRET, clean)
    redactions += count

    def redact_second_group(match: re.Match[str]) -> str:
        return f"{match.group(1)}{MEMORY_REDACTED_SECRET}"

    clean, count = MEMORY_BEARER_RE.subn(redact_second_group, clean)
    redactions += count
    clean, count = MEMORY_SECRET_ASSIGNMENT_RE.subn(redact_second_group, clean)
    redactions += count

    def redact_json_value(match: re.Match[str]) -> str:
        return f"{match.group(1)}{MEMORY_REDACTED_SECRET}{match.group(3)}"

    clean, count = MEMORY_SECRET_JSON_RE.subn(redact_json_value, clean)
    redactions += count
    return clean, redactions


def _sanitize_memory_payload(value: Any) -> tuple[Any, int]:
    if isinstance(value, str):
        return _redact_memory_text(value)
    if isinstance(value, dict):
        redactions = 0
        clean: dict[str, Any] = {}
        for key, item in value.items():
            clean_item, item_redactions = _sanitize_memory_payload(item)
            clean[key] = clean_item
            redactions += item_redactions
        return clean, redactions
    if isinstance(value, list):
        redactions = 0
        clean_items: list[Any] = []
        for item in value:
            clean_item, item_redactions = _sanitize_memory_payload(item)
            clean_items.append(clean_item)
            redactions += item_redactions
        return clean_items, redactions
    return value, 0


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> bool:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS turns (
            id TEXT PRIMARY KEY,
            thread_id TEXT,
            started_at INTEGER,
            finished_at INTEGER,
            runtime TEXT,
            model TEXT,
            speed TEXT,
            detail INTEGER,
            service_tier TEXT,
            job_budget TEXT,
            timeout_seconds INTEGER,
            prompt_chars INTEGER NOT NULL DEFAULT 0,
            response_chars INTEGER NOT NULL DEFAULT 0,
            error_chars INTEGER NOT NULL DEFAULT 0,
            prompt_preview TEXT,
            response_preview TEXT,
            error_preview TEXT,
            attachment_count INTEGER NOT NULL DEFAULT 0,
            usage_total_tokens INTEGER NOT NULL DEFAULT 0,
            success INTEGER NOT NULL DEFAULT 1,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_events (
            id TEXT PRIMARY KEY,
            thread_id TEXT,
            started_at INTEGER,
            finished_at INTEGER,
            runtime TEXT,
            model TEXT,
            speed TEXT,
            detail INTEGER,
            service_tier TEXT,
            success INTEGER NOT NULL DEFAULT 0,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            cached_input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            usage_meter_mode TEXT,
            billing_owner TEXT,
            billing_project TEXT,
            billing_scope TEXT,
            billing_unit TEXT,
            charge_ledger_kind TEXT,
            charge_display_unit TEXT,
            charge_status TEXT,
            payload_json TEXT NOT NULL
        )
        """
    )
    ensure_column(conn, "usage_events", "charge_ledger_kind", "TEXT")
    ensure_column(conn, "usage_events", "charge_display_unit", "TEXT")
    ensure_column(conn, "usage_events", "charge_status", "TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS context_cards (
            id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            scope TEXT,
            summary TEXT,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_imports (
            source_path TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            imported_at INTEGER NOT NULL,
            rows_seen INTEGER NOT NULL DEFAULT 0,
            rows_imported INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_chunks (
            chunk_id TEXT PRIMARY KEY,
            turn_id TEXT NOT NULL,
            thread_id TEXT,
            started_at INTEGER,
            source_kind TEXT,
            source_path TEXT,
            chunk_kind TEXT NOT NULL,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            text TEXT NOT NULL,
            text_preview TEXT,
            metadata_json TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_embeddings (
            chunk_id TEXT NOT NULL,
            embedding_model TEXT NOT NULL,
            dimension INTEGER NOT NULL,
            vector_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            PRIMARY KEY(chunk_id, embedding_model)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_embedding_terms (
            embedding_model TEXT NOT NULL,
            term TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            weight REAL NOT NULL,
            PRIMARY KEY(embedding_model, term, chunk_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_turns_thread_started ON turns(thread_id, started_at)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_turns_started ON turns(started_at)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_thread_started ON usage_events(thread_id, started_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_started ON usage_events(started_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_chunks_turn ON memory_chunks(turn_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_chunks_started ON memory_chunks(started_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_terms_chunk ON memory_embedding_terms(chunk_id)"
    )
    fts_enabled = ensure_fts(conn)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value, updated_at) VALUES (?, ?, ?)",
        ("schema", "norman.tui-state.v1", now_ts()),
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value, updated_at) VALUES (?, ?, ?)",
        ("fts_enabled", "1" if fts_enabled else "0", now_ts()),
    )
    conn.commit()
    return fts_enabled


def ensure_column(
    conn: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {str(row[1]) for row in rows}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_fts(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts
            USING fts5(
                id UNINDEXED,
                thread_id UNINDEXED,
                prompt,
                response,
                error
            )
            """
        )
        return True
    except sqlite3.Error:
        return False


def fts_enabled(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT 1 FROM turns_fts LIMIT 1").fetchone()
        return True
    except sqlite3.Error:
        return False


def iter_jsonl(path: Path) -> tuple[int, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    seen = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return 0, []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        seen += 1
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return seen, rows


def normalize_turn(raw: dict[str, Any], *, source_path: Path) -> dict[str, Any]:
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    prompt = str(raw.get("prompt") or "")
    response = str(raw.get("response") or "")
    error_text = str(raw.get("error") or raw.get("error_text") or "")
    payload = dict(raw)
    payload["_import_source"] = str(source_path)
    payload.setdefault("usage", usage)
    payload["id"] = state_db_id("turn", payload)
    sanitized_payload, payload_redactions = _sanitize_memory_payload(payload)
    payload = sanitized_payload if isinstance(sanitized_payload, dict) else payload
    prompt, prompt_redactions = _redact_memory_text(prompt)
    response, response_redactions = _redact_memory_text(response)
    error_text, error_redactions = _redact_memory_text(error_text)
    redactions = (
        payload_redactions + prompt_redactions + response_redactions + error_redactions
    )
    payload["memory_redacted"] = redactions > 0
    payload["memory_redactions_count"] = redactions
    payload["_prompt"] = prompt
    payload["_response"] = response
    payload["_error"] = error_text
    payload["_usage_total_tokens"] = _coerce_int(usage.get("total_tokens"))
    return payload


def _session_event_payload_type(row: dict[str, Any]) -> str:
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("type") or "").strip()


def _session_timestamp(row: dict[str, Any]) -> int | None:
    try:
        return _parse_time(str(row.get("timestamp") or ""))
    except ValueError:
        return None


def _session_message(row: dict[str, Any], key: str = "message") -> str:
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return ""
    value = payload.get(key)
    if isinstance(value, str):
        return value.strip()
    return ""


def _trim_session_text(text: str) -> str:
    if len(text) <= SESSION_TEXT_LIMIT:
        return text
    omitted = len(text) - SESSION_TEXT_LIMIT
    return f"{text[:SESSION_TEXT_LIMIT]}\n\n[truncated {omitted} chars]"


def _joined_session_messages(parts: list[str]) -> str:
    return _trim_session_text(
        "\n\n".join(part.strip() for part in parts if part.strip())
    )


def normalize_session_turns(
    rows: list[dict[str, Any]], *, source_path: Path
) -> list[dict[str, Any]]:
    session_meta: dict[str, Any] = {}
    event_counts: dict[str, int] = {}
    payload_type_counts: dict[str, int] = {}
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    last_ts: int | None = None

    def start_turn(turn_id: str, started_at: int | None) -> dict[str, Any]:
        return {
            "turn_id": turn_id,
            "started_at": started_at,
            "finished_at": started_at,
            "model": "",
            "prompts": [],
            "responses": [],
            "errors": [],
        }

    def finish_turn(finished_at: int | None) -> None:
        nonlocal current
        if current is None:
            return
        prompt = _joined_session_messages(current["prompts"])
        response = _joined_session_messages(current["responses"])
        error = _joined_session_messages(current["errors"])
        if not prompt and not response and not error:
            current = None
            return
        started_at = _coerce_int(current.get("started_at")) or _coerce_int(
            session_meta.get("started_at")
        )
        resolved_finished_at = (
            _coerce_int(finished_at)
            or _coerce_int(current.get("finished_at"))
            or started_at
        )
        raw_turn = {
            "thread_id": str(session_meta.get("session_id") or source_path.stem),
            "started_at": started_at,
            "finished_at": resolved_finished_at,
            "runtime": "codex",
            "model": str(current.get("model") or session_meta.get("model") or ""),
            "prompt": prompt,
            "response": response,
            "error": error,
            "usage": {"total_tokens": 0},
            "source_kind": "codex_session_jsonl",
            "source_path": str(source_path),
            "session_id": str(session_meta.get("session_id") or source_path.stem),
            "session_turn_id": str(current.get("turn_id") or ""),
            "session_cwd": str(session_meta.get("cwd") or ""),
            "session_originator": str(session_meta.get("originator") or ""),
            "session_source": str(session_meta.get("source") or ""),
            "session_cli_version": str(session_meta.get("cli_version") or ""),
            "event_counts": event_counts,
            "event_payload_type_counts": payload_type_counts,
        }
        turns.append(normalize_turn(raw_turn, source_path=source_path))
        current = None

    for row in rows:
        event_type = str(row.get("type") or "").strip()
        event_counts[event_type or "unknown"] = (
            event_counts.get(event_type or "unknown", 0) + 1
        )
        payload_type = _session_event_payload_type(row)
        if payload_type:
            payload_type_counts[payload_type] = (
                payload_type_counts.get(payload_type, 0) + 1
            )
        event_ts = _session_timestamp(row)
        if event_ts:
            last_ts = event_ts

        payload = row.get("payload")
        if event_type == "session_meta" and isinstance(payload, dict):
            session_meta.update(
                {
                    "session_id": payload.get("id"),
                    "cwd": payload.get("cwd"),
                    "originator": payload.get("originator"),
                    "source": payload.get("source"),
                    "cli_version": payload.get("cli_version"),
                    "model_provider": payload.get("model_provider"),
                    "started_at": _session_timestamp(
                        {"timestamp": payload.get("timestamp") or row.get("timestamp")}
                    )
                    or event_ts,
                }
            )
            continue

        if event_type == "turn_context" and isinstance(payload, dict):
            if current is not None:
                turn_id = str(payload.get("turn_id") or "")
                if (
                    not turn_id
                    or not current.get("turn_id")
                    or turn_id == current.get("turn_id")
                ):
                    current["model"] = str(
                        payload.get("model") or current.get("model") or ""
                    )
                    current["finished_at"] = event_ts or current.get("finished_at")
            continue

        if event_type != "event_msg" or not isinstance(payload, dict):
            continue

        if payload_type == "task_started":
            finish_turn(last_ts)
            current = start_turn(str(payload.get("turn_id") or ""), event_ts)
            continue

        if payload_type == "user_message":
            if current is None:
                current = start_turn(str(payload.get("turn_id") or ""), event_ts)
            message = _session_message(row)
            if message:
                current["prompts"].append(message)
            current["finished_at"] = event_ts or current.get("finished_at")
            continue

        if payload_type == "agent_message":
            if current is None:
                current = start_turn(str(payload.get("turn_id") or ""), event_ts)
            message = _session_message(row)
            if message:
                current["responses"].append(message)
            current["finished_at"] = event_ts or current.get("finished_at")
            continue

        if payload_type == "turn_aborted":
            if current is None:
                current = start_turn(str(payload.get("turn_id") or ""), event_ts)
            message = _session_message(row) or str(payload.get("reason") or "").strip()
            if message:
                current["errors"].append(message)
            current["finished_at"] = event_ts or current.get("finished_at")
            continue

        if payload_type == "task_complete":
            if current is not None:
                if not current["responses"]:
                    message = _session_message(row, "last_agent_message")
                    if message:
                        current["responses"].append(message)
                current["finished_at"] = event_ts or current.get("finished_at")
                finish_turn(event_ts)
            continue

    finish_turn(last_ts)
    return turns


def insert_turn(conn: sqlite3.Connection, turn: dict[str, Any]) -> bool:
    before = conn.total_changes
    attachments = (
        turn.get("attachments") if isinstance(turn.get("attachments"), list) else []
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO turns(
            id, thread_id, started_at, finished_at, runtime, model, speed, detail,
            service_tier, job_budget, timeout_seconds, prompt_chars, response_chars,
            error_chars, prompt_preview, response_preview, error_preview,
            attachment_count, usage_total_tokens, success, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            turn["id"],
            str(turn.get("thread_id") or ""),
            _coerce_int(turn.get("started_at")),
            _coerce_int(turn.get("finished_at")),
            str(turn.get("runtime") or ""),
            str(turn.get("model") or ""),
            str(turn.get("speed") or ""),
            _coerce_int(turn.get("detail")),
            str(turn.get("service_tier") or ""),
            str(turn.get("job_budget") or ""),
            _coerce_int(turn.get("timeout_seconds")),
            len(turn["_prompt"]),
            len(turn["_response"]),
            len(turn["_error"]),
            _preview(turn["_prompt"]),
            _preview(turn["_response"]),
            _preview(turn["_error"]),
            len(attachments),
            _coerce_int(turn["_usage_total_tokens"]),
            0 if turn["_error"] else 1,
            _json(
                {
                    key: value
                    for key, value in turn.items()
                    if not str(key).startswith("_")
                }
            ),
        ),
    )
    if fts_enabled(conn):
        conn.execute("DELETE FROM turns_fts WHERE id = ?", (turn["id"],))
        conn.execute(
            """
            INSERT OR REPLACE INTO turns_fts(id, thread_id, prompt, response, error)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                turn["id"],
                str(turn.get("thread_id") or ""),
                turn["_prompt"],
                turn["_response"],
                turn["_error"],
            ),
        )
    return conn.total_changes > before


def normalize_usage(raw: dict[str, Any], *, source_path: Path) -> dict[str, Any]:
    payload = dict(raw)
    payload["_import_source"] = str(source_path)
    payload["id"] = state_db_id("usage", payload)
    payload["runtime"] = normalize_runtime(payload.get("runtime"))
    payload["charge_ledger_kind"] = usage_charge_ledger_kind(payload)
    payload["charge_display_unit"] = str(
        payload.get("charge_display_unit") or ""
    ).strip() or usage_charge_display_unit(payload["charge_ledger_kind"])
    payload["charge_status"] = usage_charge_status(payload)
    return payload


def insert_usage(conn: sqlite3.Connection, usage: dict[str, Any]) -> bool:
    before = conn.total_changes
    conn.execute(
        """
        INSERT OR REPLACE INTO usage_events(
            id, thread_id, started_at, finished_at, runtime, model, speed, detail,
            service_tier, success, input_tokens, cached_input_tokens, output_tokens,
            reasoning_output_tokens, total_tokens, usage_meter_mode, billing_owner,
            billing_project, billing_scope, billing_unit, charge_ledger_kind,
            charge_display_unit, charge_status, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            usage["id"],
            str(usage.get("thread_id") or ""),
            _coerce_int(usage.get("started_at")),
            _coerce_int(usage.get("finished_at")),
            str(usage.get("runtime") or ""),
            str(usage.get("model") or ""),
            str(usage.get("speed") or ""),
            _coerce_int(usage.get("detail")),
            str(usage.get("service_tier") or ""),
            1 if usage.get("success") else 0,
            _coerce_int(usage.get("input_tokens")),
            _coerce_int(usage.get("cached_input_tokens")),
            _coerce_int(usage.get("output_tokens")),
            _coerce_int(usage.get("reasoning_output_tokens")),
            _coerce_int(usage.get("total_tokens")),
            str(usage.get("usage_meter_mode") or ""),
            str(usage.get("billing_owner") or ""),
            str(usage.get("billing_project") or ""),
            str(usage.get("billing_scope") or ""),
            str(usage.get("billing_unit") or ""),
            str(usage.get("charge_ledger_kind") or ""),
            str(usage.get("charge_display_unit") or ""),
            str(usage.get("charge_status") or ""),
            _json(
                {
                    key: value
                    for key, value in usage.items()
                    if not str(key).startswith("_")
                }
            ),
        ),
    )
    return conn.total_changes > before


def import_history_files(conn: sqlite3.Connection, paths: list[Path]) -> dict[str, Any]:
    summary = {"files": 0, "rows_seen": 0, "rows_imported": 0}
    for path in paths:
        seen, rows = iter_jsonl(path)
        imported = 0
        for row in rows:
            if insert_turn(conn, normalize_turn(row, source_path=path)):
                imported += 1
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_imports(
                source_path, kind, imported_at, rows_seen, rows_imported
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (str(path), "history", now_ts(), seen, imported),
        )
        summary["files"] += 1
        summary["rows_seen"] += seen
        summary["rows_imported"] += imported
    conn.commit()
    return summary


def import_usage_files(conn: sqlite3.Connection, paths: list[Path]) -> dict[str, Any]:
    summary = {"files": 0, "rows_seen": 0, "rows_imported": 0}
    for path in paths:
        seen, rows = iter_jsonl(path)
        imported = 0
        for row in rows:
            if insert_usage(conn, normalize_usage(row, source_path=path)):
                imported += 1
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_imports(
                source_path, kind, imported_at, rows_seen, rows_imported
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (str(path), "usage", now_ts(), seen, imported),
        )
        summary["files"] += 1
        summary["rows_seen"] += seen
        summary["rows_imported"] += imported
    conn.commit()
    return summary


def import_session_files(conn: sqlite3.Connection, paths: list[Path]) -> dict[str, Any]:
    summary = {"files": 0, "rows_seen": 0, "rows_imported": 0}
    for path in paths:
        seen, rows = iter_jsonl(path)
        imported = 0
        for turn in normalize_session_turns(rows, source_path=path):
            if insert_turn(conn, turn):
                imported += 1
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_imports(
                source_path, kind, imported_at, rows_seen, rows_imported
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (str(path), "session", now_ts(), seen, imported),
        )
        summary["files"] += 1
        summary["rows_seen"] += seen
        summary["rows_imported"] += imported
    conn.commit()
    return summary


def _decode_payload_json(value: Any) -> dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def usage_event_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, thread_id, started_at, finished_at, runtime, model, speed, detail,
               service_tier, success, input_tokens, cached_input_tokens,
               output_tokens, reasoning_output_tokens, total_tokens,
               usage_meter_mode, billing_owner, billing_project, billing_scope,
               billing_unit, charge_ledger_kind, charge_display_unit,
               charge_status, payload_json
        FROM usage_events
        ORDER BY COALESCE(started_at, 0), COALESCE(finished_at, 0), id
        """
    ).fetchall()
    events: list[dict[str, Any]] = []
    for row in rows:
        row_payload = dict(row)
        payload = _decode_payload_json(row_payload.pop("payload_json", ""))
        for key, value in row_payload.items():
            if isinstance(value, str):
                if value.strip() or not str(payload.get(key) or "").strip():
                    payload[key] = value
            elif value is None:
                payload.setdefault(key, value)
            else:
                payload[key] = value
        payload["payload_json"] = row["payload_json"]
        events.append(payload)
    return events


def normalize_usage_for_audit(value: dict[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    for key in (
        "id",
        "thread_id",
        "runtime",
        "model",
        "speed",
        "service_tier",
        "usage_meter_mode",
        "billing_owner",
        "billing_project",
        "billing_scope",
        "billing_unit",
        "agent_group",
        "provider_surface",
        "observed_service_tier",
        "resolved_service_tier",
        "charge_ledger_kind",
        "charge_display_unit",
        "charge_status",
    ):
        payload[key] = str(payload.get(key) or "").strip()
    for key in (
        "started_at",
        "finished_at",
        "detail",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
        "raw_input_tokens",
        "raw_cached_input_tokens",
        "raw_output_tokens",
        "raw_reasoning_output_tokens",
        "raw_total_tokens",
        "cumulative_total_tokens",
    ):
        payload[key] = _coerce_int(payload.get(key))
    payload["runtime"] = normalize_runtime(payload.get("runtime"))
    payload["charge_ledger_kind"] = usage_charge_ledger_kind(payload)
    payload["charge_display_unit"] = payload.get(
        "charge_display_unit"
    ) or usage_charge_display_unit(payload["charge_ledger_kind"])
    payload["charge_status"] = usage_charge_status(payload)
    payload["success"] = _coerce_bool(payload.get("success"))
    return payload


def _usage_raw_counter(entry: dict[str, Any], key: str) -> int:
    raw_value = _coerce_int(entry.get(f"raw_{key}"))
    if raw_value > 0:
        return raw_value
    return _coerce_int(entry.get(key))


def _usage_scope_key(entry: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(entry.get("thread_id") or "").strip(),
        str(entry.get("runtime") or "").strip(),
        str(entry.get("model") or "").strip(),
        str(entry.get("provider_surface") or "").strip(),
    )


def usage_entry_with_effective_delta(
    entry: dict[str, Any],
    previous_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = normalize_usage_for_audit(entry)
    if current.get("usage_meter_mode") in {"cumulative_delta", "cumulative_baseline"}:
        return current

    raw_counters = {
        "input_tokens": _usage_raw_counter(current, "input_tokens"),
        "cached_input_tokens": _usage_raw_counter(current, "cached_input_tokens"),
        "output_tokens": _usage_raw_counter(current, "output_tokens"),
        "reasoning_output_tokens": _usage_raw_counter(
            current, "reasoning_output_tokens"
        ),
        "total_tokens": _usage_raw_counter(current, "total_tokens"),
    }
    for key, value in raw_counters.items():
        current[f"raw_{key}"] = value
    current["cumulative_total_tokens"] = raw_counters["total_tokens"]

    if raw_counters["total_tokens"] < USAGE_CUMULATIVE_DETECT_MIN_TOKENS:
        current["usage_meter_mode"] = current.get("usage_meter_mode") or "per_turn"
        return current

    if (
        previous_entry is None
        and raw_counters["total_tokens"] >= USAGE_CUMULATIVE_BASELINE_MIN_TOKENS
    ):
        current.update(
            {
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
                "total_tokens": 0,
                "usage_meter_mode": "cumulative_baseline",
            }
        )
        return current
    if previous_entry is None:
        current["usage_meter_mode"] = current.get("usage_meter_mode") or "per_turn"
        return current

    previous = normalize_usage_for_audit(previous_entry)
    previous_raw = {
        "input_tokens": _usage_raw_counter(previous, "input_tokens"),
        "cached_input_tokens": _usage_raw_counter(previous, "cached_input_tokens"),
        "output_tokens": _usage_raw_counter(previous, "output_tokens"),
        "reasoning_output_tokens": _usage_raw_counter(
            previous, "reasoning_output_tokens"
        ),
        "total_tokens": _usage_raw_counter(previous, "total_tokens"),
    }
    counter_did_not_advance = (
        raw_counters["total_tokens"] <= previous_raw["total_tokens"]
    )
    counter_component_reset = any(
        raw_counters[key] < previous_raw[key] for key in raw_counters
    )
    if counter_did_not_advance or counter_component_reset:
        if raw_counters["total_tokens"] >= USAGE_CUMULATIVE_BASELINE_MIN_TOKENS:
            current.update(
                {
                    "input_tokens": 0,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "total_tokens": 0,
                    "usage_meter_mode": "cumulative_baseline",
                }
            )
            return current
        current["usage_meter_mode"] = current.get("usage_meter_mode") or "per_turn"
        return current

    deltas = {
        key: max(0, raw_counters[key] - previous_raw[key]) for key in raw_counters
    }
    current.update(
        {
            "input_tokens": deltas["input_tokens"],
            "cached_input_tokens": deltas["cached_input_tokens"],
            "output_tokens": deltas["output_tokens"],
            "reasoning_output_tokens": deltas["reasoning_output_tokens"],
            "total_tokens": deltas["total_tokens"]
            or deltas["input_tokens"] + deltas["output_tokens"],
            "usage_meter_mode": "cumulative_delta",
        }
    )
    return current


def usage_entries_with_effective_deltas(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    effective: list[dict[str, Any]] = []
    previous_by_scope: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for raw_entry in entries:
        entry = normalize_usage_for_audit(raw_entry)
        scope = _usage_scope_key(entry)
        previous = previous_by_scope.get(scope) if scope[0] else None
        effective_entry = usage_entry_with_effective_delta(entry, previous)
        effective.append(effective_entry)
        if scope[0] and effective_entry.get("usage_meter_mode") in {
            "cumulative_baseline",
            "cumulative_delta",
        }:
            previous_by_scope[scope] = effective_entry
    return effective


def default_usage_summary() -> dict[str, int]:
    return {
        "events": 0,
        "successful_events": 0,
        "failed_events": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
        "last_event_at": 0,
    }


def summarize_usage_events(
    entries: list[dict[str, Any]], *, since_ts: int = 0
) -> dict[str, int]:
    summary = dict(default_usage_summary())
    for raw_entry in entries:
        entry = normalize_usage_for_audit(raw_entry)
        event_at = _coerce_int(entry.get("finished_at")) or _coerce_int(
            entry.get("started_at")
        )
        if since_ts and event_at and event_at < since_ts:
            continue
        summary["events"] += 1
        if entry["success"]:
            summary["successful_events"] += 1
        else:
            summary["failed_events"] += 1
        summary["input_tokens"] += entry["input_tokens"]
        summary["cached_input_tokens"] += entry["cached_input_tokens"]
        summary["output_tokens"] += entry["output_tokens"]
        summary["reasoning_output_tokens"] += entry["reasoning_output_tokens"]
        summary["total_tokens"] += entry["total_tokens"]
        summary["last_event_at"] = max(summary["last_event_at"], event_at)
    return summary


def _count_by_key(entries: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        value = str(entry.get(key) or "").strip() or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _summarize_tokens_by_key(
    entries: list[dict[str, Any]], key: str, *, limit: int = USAGE_AUDIT_GROUP_LIMIT
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for entry in entries:
        value = str(entry.get(key) or "").strip() or "unknown"
        bucket = grouped.setdefault(value, {"key": value, **default_usage_summary()})
        summary = summarize_usage_events([entry])
        for summary_key, summary_value in summary.items():
            if summary_key == "last_event_at":
                bucket[summary_key] = max(bucket[summary_key], summary_value)
            else:
                bucket[summary_key] += summary_value
    return sorted(
        grouped.values(),
        key=lambda item: (-_coerce_int(item.get("total_tokens")), str(item["key"])),
    )[: max(1, limit)]


def usage_audit_entries(
    raw_entries: list[dict[str, Any]],
    *,
    since_ts: int | None = None,
    window_seconds: int = USAGE_WINDOW_SECONDS,
    source: str = "entries",
) -> dict[str, Any]:
    effective_entries = usage_entries_with_effective_deltas(raw_entries)
    effective_since = (
        since_ts if since_ts is not None else max(0, now_ts() - window_seconds)
    )
    raw_summary = summarize_usage_events(raw_entries)
    effective_summary = summarize_usage_events(effective_entries)
    window_summary = summarize_usage_events(effective_entries, since_ts=effective_since)
    raw_total = max(0, raw_summary["total_tokens"])
    effective_total = max(0, effective_summary["total_tokens"])
    if effective_total:
        raw_to_effective_ratio = round(raw_total / effective_total, 3)
    elif raw_total:
        raw_to_effective_ratio = None
    else:
        raw_to_effective_ratio = 1.0
    return {
        "schema": "norman.tui.usage-audit.v1",
        "source": source,
        "events": len(raw_entries),
        "window_seconds": max(0, int(window_seconds or 0)),
        "since_ts": effective_since,
        "raw": raw_summary,
        "effective": effective_summary,
        "window": window_summary,
        "raw_to_effective_ratio": raw_to_effective_ratio,
        "meter_modes": _count_by_key(effective_entries, "usage_meter_mode"),
        "charge_ledger_kinds": _count_by_key(effective_entries, "charge_ledger_kind"),
        "charge_display_units": _count_by_key(effective_entries, "charge_display_unit"),
        "charge_statuses": _count_by_key(effective_entries, "charge_status"),
        "billing_units": _summarize_tokens_by_key(effective_entries, "billing_unit"),
        "models": _summarize_tokens_by_key(effective_entries, "model"),
        "service_tiers": _summarize_tokens_by_key(effective_entries, "service_tier"),
        "zero_effective_events": sum(
            1
            for entry in effective_entries
            if _coerce_int(entry.get("total_tokens")) <= 0
        ),
        "unknown_meter_events": sum(
            1
            for entry in effective_entries
            if not str(entry.get("usage_meter_mode") or "").strip()
            or str(entry.get("usage_meter_mode") or "").strip() == "unknown"
        ),
        "note": (
            "Raw totals are stored counters. Effective totals normalize suspected "
            "cumulative counters into baselines and deltas before cost reasoning. "
            "Credit ledgers are local Codex consumption estimates, not credit-card "
            "charges, unless explicitly invoice reconciled."
        ),
    }


def usage_audit(
    conn: sqlite3.Connection,
    *,
    since_ts: int | None = None,
    window_seconds: int = USAGE_WINDOW_SECONDS,
) -> dict[str, Any]:
    return usage_audit_entries(
        usage_event_rows(conn),
        since_ts=since_ts,
        window_seconds=window_seconds,
        source="state_db",
    )


def usage_audit_from_files(
    paths: list[Path],
    *,
    since_ts: int | None = None,
    window_seconds: int = USAGE_WINDOW_SECONDS,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    files_seen = 0
    rows_seen = 0
    for path in paths:
        seen, file_rows = iter_jsonl(path)
        files_seen += 1
        rows_seen += seen
        rows.extend(file_rows)
    audit = usage_audit_entries(
        rows,
        since_ts=since_ts,
        window_seconds=window_seconds,
        source="usage_files",
    )
    audit["files"] = [str(path) for path in paths]
    audit["files_seen"] = files_seen
    audit["rows_seen"] = rows_seen
    return audit


def render_usage_audit_md(audit: dict[str, Any]) -> str:
    raw = audit.get("raw") if isinstance(audit.get("raw"), dict) else {}
    effective = (
        audit.get("effective") if isinstance(audit.get("effective"), dict) else {}
    )
    window = audit.get("window") if isinstance(audit.get("window"), dict) else {}
    meter_modes = (
        audit.get("meter_modes") if isinstance(audit.get("meter_modes"), dict) else {}
    )
    charge_ledger_kinds = (
        audit.get("charge_ledger_kinds")
        if isinstance(audit.get("charge_ledger_kinds"), dict)
        else {}
    )
    charge_display_units = (
        audit.get("charge_display_units")
        if isinstance(audit.get("charge_display_units"), dict)
        else {}
    )
    charge_statuses = (
        audit.get("charge_statuses")
        if isinstance(audit.get("charge_statuses"), dict)
        else {}
    )
    status_keys = {str(key) for key in charge_statuses}
    card_charge = (
        "no"
        if status_keys and status_keys <= {"not_invoice_reconciled"}
        else "yes/reconciled"
        if "invoice_reconciled" in status_keys
        else "unknown"
    )
    if charge_display_units.get("credits"):
        display_basis = "personal Codex credits; API-dollar values are comparison only"
    elif charge_display_units.get("usd_equivalent"):
        display_basis = "USD equivalent; not an invoice unless reconciled"
    else:
        display_basis = "tokens"
    lines = [
        "# TUI Usage Audit",
        "",
        f"Source: `{audit.get('source', 'unknown')}`",
        f"Events: `{audit.get('events', 0)}`",
        f"Raw total tokens: `{raw.get('total_tokens', 0)}`",
        f"Effective total tokens: `{effective.get('total_tokens', 0)}`",
        f"Window effective tokens: `{window.get('total_tokens', 0)}`",
        f"Raw/effective ratio: `{audit.get('raw_to_effective_ratio')}`",
        f"Meter modes: `{json.dumps(meter_modes, sort_keys=True)}`",
        f"Charge ledger kinds: `{json.dumps(charge_ledger_kinds, sort_keys=True)}`",
        f"Charge display units: `{json.dumps(charge_display_units, sort_keys=True)}`",
        f"Charge statuses: `{json.dumps(charge_statuses, sort_keys=True)}`",
        f"Card charge: `{card_charge}`",
        f"Display basis: `{display_basis}`",
        "",
        "| Group | Key | Events | Effective Tokens | Last Event |",
        "|---|---|---:|---:|---:|",
    ]
    for group_key in ("billing_units", "models", "service_tiers"):
        for row in audit.get(group_key, []):
            lines.append(
                "| {group} | {key} | {events} | {tokens} | {last} |".format(
                    group=group_key,
                    key=str(row.get("key") or "unknown").replace("|", "/"),
                    events=row.get("events", 0),
                    tokens=row.get("total_tokens", 0),
                    last=row.get("last_event_at", 0),
                )
            )
    lines.extend(["", str(audit.get("note") or "")])
    return "\n".join(lines) + "\n"


def discover_history_files(state_dir: Path) -> list[Path]:
    patterns = [
        "history.jsonl",
        "history.jsonl.bak-*",
        "recovery_*/history.jsonl",
    ]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path for path in state_dir.glob(pattern) if path.is_file())
    return sorted(set(files))


def discover_usage_files(state_dir: Path) -> list[Path]:
    patterns = [
        "usage.jsonl",
        "usage-ledger.jsonl",
        "recovery_*/usage.jsonl",
        "recovery_*/usage-ledger.jsonl",
    ]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path for path in state_dir.glob(pattern) if path.is_file())
    return sorted(set(files))


def discover_session_files(codex_home: Path) -> list[Path]:
    sessions_dir = codex_home / "sessions"
    if not sessions_dir.is_dir():
        return []
    return sorted(path for path in sessions_dir.glob("**/*.jsonl") if path.is_file())


def rebuild_fts(conn: sqlite3.Connection) -> dict[str, Any]:
    if not fts_enabled(conn):
        return {"fts_enabled": False, "rows": 0}
    conn.execute("DELETE FROM turns_fts")
    rows = conn.execute("SELECT id, thread_id, payload_json FROM turns").fetchall()
    count = 0
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            payload = {}
        conn.execute(
            """
            INSERT OR REPLACE INTO turns_fts(id, thread_id, prompt, response, error)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["thread_id"],
                str(payload.get("prompt") or ""),
                str(payload.get("response") or ""),
                str(payload.get("error") or payload.get("error_text") or ""),
            ),
        )
        count += 1
    conn.commit()
    return {"fts_enabled": True, "rows": count}


def _memory_text_chunks(text: str) -> list[str]:
    clean = str(text or "").strip()
    if not clean:
        return []
    if len(clean) <= MEMORY_CHUNK_CHARS:
        return [clean]
    chunks: list[str] = []
    step = max(1, MEMORY_CHUNK_CHARS - MEMORY_CHUNK_OVERLAP)
    for start in range(0, len(clean), step):
        chunk = clean[start : start + MEMORY_CHUNK_CHARS].strip()
        if chunk:
            chunks.append(chunk)
        if start + MEMORY_CHUNK_CHARS >= len(clean):
            break
    return chunks


def _memory_vector_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9_][a-z0-9_.-]*", str(text or "").lower())
    return [
        token
        for token in tokens
        if len(token) >= MEMORY_VECTOR_MIN_TOKEN_LEN
        and token not in MEMORY_VECTOR_STOPWORDS
    ]


def _memory_hash_vector(text: str) -> dict[str, float]:
    counts: dict[str, float] = {}
    for token in _memory_vector_tokens(text):
        counts[token] = counts.get(token, 0.0) + 1.0
    norm = sum(value * value for value in counts.values()) ** 0.5
    if norm <= 0:
        return {}
    return {token: round(value / norm, 8) for token, value in sorted(counts.items())}


def _turn_text_payload(row: sqlite3.Row) -> dict[str, Any]:
    payload = _decode_payload_json(row["payload_json"])
    payload.setdefault("prompt", row["prompt_preview"])
    payload.setdefault("response", row["response_preview"])
    payload.setdefault("error", row["error_preview"])
    return payload


def _iter_turn_chunks(row: sqlite3.Row) -> list[dict[str, Any]]:
    payload = _turn_text_payload(row)
    chunks: list[dict[str, Any]] = []
    for chunk_kind in ("prompt", "response", "error"):
        text = str(
            payload.get(chunk_kind) or payload.get(f"{chunk_kind}_text") or ""
        ).strip()
        for chunk_index, chunk_text in enumerate(_memory_text_chunks(text)):
            sha = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
            chunk_id = state_db_id(
                "memory_chunk",
                {
                    "thread_id": row["thread_id"],
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                    "prompt": row["id"],
                    "response": f"{chunk_kind}:{chunk_index}:{sha}",
                },
            )
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "turn_id": row["id"],
                    "thread_id": row["thread_id"],
                    "started_at": _coerce_int(row["started_at"]),
                    "source_kind": str(payload.get("source_kind") or ""),
                    "source_path": str(payload.get("source_path") or ""),
                    "chunk_kind": chunk_kind,
                    "chunk_index": chunk_index,
                    "text": chunk_text,
                    "text_preview": _preview(chunk_text),
                    "metadata_json": _json(
                        {
                            "turn_id": row["id"],
                            "thread_id": row["thread_id"],
                            "started_at": row["started_at"],
                            "finished_at": row["finished_at"],
                            "runtime": row["runtime"],
                            "model": row["model"],
                            "source_kind": payload.get("source_kind"),
                            "source_path": payload.get("source_path"),
                            "session_id": payload.get("session_id"),
                            "session_turn_id": payload.get("session_turn_id"),
                            "session_cwd": payload.get("session_cwd"),
                        }
                    ),
                    "sha256": sha,
                }
            )
    return chunks


def rebuild_memory_vectors(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    conn.execute("DELETE FROM memory_embedding_terms")
    conn.execute("DELETE FROM memory_embeddings")
    conn.execute("DELETE FROM memory_chunks")
    sql = """
        SELECT id, thread_id, started_at, finished_at, runtime, model,
               prompt_preview, response_preview, error_preview, payload_json
        FROM turns
        ORDER BY COALESCE(started_at, 0) DESC, id
    """
    params: list[Any] = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(1, int(limit)))
    rows = conn.execute(sql, params).fetchall()
    chunk_count = 0
    term_count = 0
    created_at = now_ts()
    for row in rows:
        for chunk in _iter_turn_chunks(row):
            vector = _memory_hash_vector(chunk["text"])
            if not vector:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_chunks(
                    chunk_id, turn_id, thread_id, started_at, source_kind,
                    source_path, chunk_kind, chunk_index, text, text_preview,
                    metadata_json, sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk["chunk_id"],
                    chunk["turn_id"],
                    chunk["thread_id"],
                    chunk["started_at"],
                    chunk["source_kind"],
                    chunk["source_path"],
                    chunk["chunk_kind"],
                    chunk["chunk_index"],
                    chunk["text"],
                    chunk["text_preview"],
                    chunk["metadata_json"],
                    chunk["sha256"],
                    created_at,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_embeddings(
                    chunk_id, embedding_model, dimension, vector_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    chunk["chunk_id"],
                    MEMORY_VECTOR_MODEL,
                    MEMORY_VECTOR_DIMENSION,
                    _json(vector),
                    created_at,
                ),
            )
            conn.executemany(
                """
                INSERT OR REPLACE INTO memory_embedding_terms(
                    embedding_model, term, chunk_id, weight
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (MEMORY_VECTOR_MODEL, term, chunk["chunk_id"], weight)
                    for term, weight in vector.items()
                ],
            )
            chunk_count += 1
            term_count += len(vector)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value, updated_at) VALUES (?, ?, ?)",
        ("memory_vector_model", MEMORY_VECTOR_MODEL, created_at),
    )
    conn.commit()
    return {
        "embedding_model": MEMORY_VECTOR_MODEL,
        "dimension": MEMORY_VECTOR_DIMENSION,
        "turns_seen": len(rows),
        "chunks": chunk_count,
        "terms": term_count,
    }


def vector_search(
    conn: sqlite3.Connection,
    *,
    query: str,
    since: int | None = None,
    until: int | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    query_vector = _memory_hash_vector(query)
    if not query_vector:
        return {
            "mode": "vector",
            "embedding_model": MEMORY_VECTOR_MODEL,
            "query": query,
            "rows": [],
        }
    limit = max(1, min(200, int(limit or DEFAULT_LIMIT)))
    term_rows = conn.execute(
        f"""
        SELECT term, chunk_id, weight
        FROM memory_embedding_terms
        WHERE embedding_model = ?
          AND term IN ({",".join("?" for _ in query_vector)})
        """,
        [MEMORY_VECTOR_MODEL, *query_vector.keys()],
    ).fetchall()
    scores: dict[str, float] = {}
    for row in term_rows:
        scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0.0) + (
            float(row["weight"]) * query_vector[str(row["term"])]
        )
    if not scores:
        return {
            "mode": "vector",
            "embedding_model": MEMORY_VECTOR_MODEL,
            "query": query,
            "rows": [],
        }
    candidates = sorted(scores.items(), key=lambda item: item[1], reverse=True)[
        : limit * 8
    ]
    placeholders = ",".join("?" for _ in candidates)
    clauses = [f"chunk_id IN ({placeholders})"]
    args: list[Any] = [chunk_id for chunk_id, _score in candidates]
    if since is not None:
        clauses.append("COALESCE(started_at, 0) >= ?")
        args.append(since)
    if until is not None:
        clauses.append("COALESCE(started_at, 0) <= ?")
        args.append(until)
    rows = conn.execute(
        f"""
        SELECT chunk_id, turn_id, thread_id, started_at, source_kind, source_path,
               chunk_kind, chunk_index, text_preview, metadata_json
        FROM memory_chunks
        WHERE {" AND ".join(clauses)}
        """,
        args,
    ).fetchall()
    row_by_id = {row["chunk_id"]: dict(row) for row in rows}
    result_rows: list[dict[str, Any]] = []
    for chunk_id, score in candidates:
        row = row_by_id.get(chunk_id)
        if not row:
            continue
        row["vector_score"] = round(score, 8)
        result_rows.append(row)
        if len(result_rows) >= limit:
            break
    return {
        "mode": "vector",
        "embedding_model": MEMORY_VECTOR_MODEL,
        "dimension": MEMORY_VECTOR_DIMENSION,
        "query": query,
        "rows": result_rows,
    }


def hybrid_search(
    conn: sqlite3.Connection,
    *,
    query: str,
    since: int | None = None,
    until: int | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    return {
        "mode": "hybrid",
        "query": query,
        "fts": search_turns(conn, query=query, since=since, until=until, limit=limit),
        "metadata": metadata_search(
            conn, query=query, since=since, until=until, limit=limit
        ),
        "vector": vector_search(
            conn, query=query, since=since, until=until, limit=limit
        ),
    }


def _fts_query(query: str) -> str:
    terms = re.findall(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", query or "")
    if not terms:
        return ""
    return " ".join(f'"{term}"' for term in terms[:12])


def search_turns(
    conn: sqlite3.Connection,
    *,
    query: str,
    since: int | None = None,
    until: int | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    args: list[Any] = []
    time_clause = ""
    if since is not None:
        time_clause += " AND COALESCE(t.started_at, 0) >= ?"
        args.append(since)
    if until is not None:
        time_clause += " AND COALESCE(t.started_at, 0) <= ?"
        args.append(until)
    limit = max(1, min(200, int(limit or DEFAULT_LIMIT)))
    if fts_enabled(conn):
        fts_query = _fts_query(query)
        if not fts_query:
            return {"mode": "fts5", "query": query, "rows": []}
        sql = f"""
            SELECT t.id, t.thread_id, t.started_at, t.finished_at, t.runtime,
                   t.model, t.service_tier, t.usage_total_tokens, t.success,
                   t.prompt_preview, t.response_preview, t.error_preview,
                   bm25(turns_fts) AS rank
            FROM turns_fts
            JOIN turns t ON t.id = turns_fts.id
            WHERE turns_fts MATCH ? {time_clause}
            ORDER BY rank, COALESCE(t.started_at, 0) DESC
            LIMIT ?
        """
        rows = conn.execute(sql, [fts_query, *args, limit]).fetchall()
        mode = "fts5"
    else:
        like = f"%{query}%"
        sql = f"""
            SELECT id, thread_id, started_at, finished_at, runtime, model,
                   service_tier, usage_total_tokens, success, prompt_preview,
                   response_preview, error_preview, 0 AS rank
            FROM turns t
            WHERE (
                prompt_preview LIKE ? OR response_preview LIKE ?
                OR error_preview LIKE ? OR payload_json LIKE ?
            ) {time_clause}
            ORDER BY COALESCE(started_at, 0) DESC
            LIMIT ?
        """
        rows = conn.execute(sql, [like, like, like, like, *args, limit]).fetchall()
        mode = "like"
    return {
        "mode": mode,
        "query": query,
        "rows": [dict(row) for row in rows],
    }


def metadata_search(
    conn: sqlite3.Connection,
    *,
    query: str,
    since: int | None = None,
    until: int | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    clean = str(query or "").strip()
    if not clean:
        return {"mode": "metadata", "query": query, "rows": []}
    args: list[Any] = [clean, clean, f"%{clean}%"]
    time_clause = ""
    if since is not None:
        time_clause += " AND COALESCE(started_at, 0) >= ?"
        args.append(since)
    if until is not None:
        time_clause += " AND COALESCE(started_at, 0) <= ?"
        args.append(until)
    candidate_rows = conn.execute(
        f"""
        SELECT id, thread_id, started_at, finished_at, runtime, model,
               service_tier, usage_total_tokens, success, prompt_preview,
               response_preview, error_preview, payload_json
        FROM turns
        WHERE (id = ? OR thread_id = ? OR payload_json LIKE ?) {time_clause}
        ORDER BY COALESCE(started_at, 0) DESC
        LIMIT ?
        """,
        [*args, max(50, min(1000, int(limit or DEFAULT_LIMIT) * 20))],
    ).fetchall()
    rows: list[dict[str, Any]] = []
    clean_lower = clean.lower()
    metadata_keys = (
        "source_kind",
        "source_path",
        "session_id",
        "session_turn_id",
        "session_cwd",
        "session_originator",
        "session_source",
        "session_cli_version",
        "billing_unit",
    )
    for row in candidate_rows:
        result_row = dict(row)
        payload = _decode_payload_json(result_row.get("payload_json"))
        matches: list[str] = []
        if clean == str(result_row.get("id") or ""):
            matches.append("id")
        if clean == str(result_row.get("thread_id") or ""):
            matches.append("thread_id")
        for key in metadata_keys:
            value = payload.get(key)
            if value is not None and clean_lower in str(value).lower():
                matches.append(key)
        if not matches:
            continue
        result_row["metadata_matches"] = matches
        rows.append(result_row)
        if len(rows) >= max(1, min(200, int(limit or DEFAULT_LIMIT))):
            break
    return {
        "mode": "metadata",
        "query": query,
        "rows": rows,
    }


def time_series(
    conn: sqlite3.Connection,
    *,
    bucket: str,
    since: int | None = None,
    until: int | None = None,
) -> dict[str, Any]:
    if bucket not in {"hour", "day"}:
        raise ValueError("bucket must be hour or day")
    fmt = "%Y-%m-%dT%H:00:00Z" if bucket == "hour" else "%Y-%m-%d"
    clauses = ["started_at > 0"]
    args: list[Any] = []
    if since is not None:
        clauses.append("started_at >= ?")
        args.append(since)
    if until is not None:
        clauses.append("started_at <= ?")
        args.append(until)
    where = " AND ".join(clauses)
    turn_rows = conn.execute(
        f"""
        SELECT strftime(?, started_at, 'unixepoch') AS bucket,
               COUNT(*) AS turns,
               SUM(usage_total_tokens) AS turn_tokens,
               SUM(CASE WHEN success THEN 1 ELSE 0 END) AS successful_turns
        FROM turns
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        [fmt, *args],
    ).fetchall()
    usage_rows = conn.execute(
        f"""
        SELECT strftime(?, started_at, 'unixepoch') AS bucket,
               COUNT(*) AS usage_events,
               SUM(input_tokens) AS input_tokens,
               SUM(cached_input_tokens) AS cached_input_tokens,
               SUM(output_tokens) AS output_tokens,
               SUM(total_tokens) AS total_tokens
        FROM usage_events
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        [fmt, *args],
    ).fetchall()
    merged: dict[str, dict[str, Any]] = {}
    for row in turn_rows:
        merged.setdefault(row["bucket"], {}).update(dict(row))
    for row in usage_rows:
        merged.setdefault(row["bucket"], {}).update(dict(row))
    return {
        "bucket": bucket,
        "rows": [merged[key] for key in sorted(merged)],
    }


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    turn = conn.execute(
        """
        SELECT COUNT(*) AS turns,
               MIN(started_at) AS first_turn_at,
               MAX(started_at) AS last_turn_at,
               SUM(usage_total_tokens) AS turn_tokens
        FROM turns
        """
    ).fetchone()
    usage = conn.execute(
        """
        SELECT COUNT(*) AS usage_events,
               SUM(input_tokens) AS input_tokens,
               SUM(cached_input_tokens) AS cached_input_tokens,
               SUM(output_tokens) AS output_tokens,
               SUM(total_tokens) AS total_tokens
        FROM usage_events
        """
    ).fetchone()
    effective_usage = summarize_usage_events(
        usage_entries_with_effective_deltas(usage_event_rows(conn))
    )
    imports = conn.execute(
        """
        SELECT kind, COUNT(*) AS files, SUM(rows_seen) AS rows_seen,
               SUM(rows_imported) AS rows_imported
        FROM memory_imports
        GROUP BY kind
        ORDER BY kind
        """
    ).fetchall()
    vector = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM memory_chunks) AS chunks,
            (SELECT COUNT(*) FROM memory_embeddings) AS embeddings,
            (SELECT COUNT(*) FROM memory_embedding_terms) AS terms,
            (SELECT COUNT(DISTINCT turn_id) FROM memory_chunks) AS indexed_turns
        """
    ).fetchone()
    return {
        "fts_enabled": fts_enabled(conn),
        "turns": dict(turn),
        "usage": dict(usage),
        "usage_effective": effective_usage,
        "imports": [dict(row) for row in imports],
        "memory_vector": dict(vector),
    }


def render_search_md(result: dict[str, Any]) -> str:
    lines = [
        f"# TUI Memory Search ({result.get('mode')})",
        "",
        f"Query: `{result.get('query')}`",
        "",
        "| Started | Thread | Tokens | Prompt | Response |",
        "|---:|---|---:|---|---|",
    ]
    for row in result.get("rows", []):
        lines.append(
            "| {started} | {thread} | {tokens} | {prompt} | {response} |".format(
                started=row.get("started_at") or "",
                thread=str(row.get("thread_id") or "")[:16],
                tokens=row.get("usage_total_tokens") or 0,
                prompt=str(row.get("prompt_preview") or "").replace("|", "/"),
                response=str(row.get("response_preview") or "").replace("|", "/"),
            )
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import and query local TUI SQLite memory."
    )
    parser.add_argument("--db", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init")

    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("--history", type=Path, action="append", default=[])
    import_parser.add_argument("--usage", type=Path, action="append", default=[])
    import_parser.add_argument("--session", type=Path, action="append", default=[])
    import_parser.add_argument("--state-dir", type=Path)
    import_parser.add_argument(
        "--codex-home",
        type=Path,
        action="append",
        default=[],
        help="Import web-bridge history/usage and sessions under a CODEX_HOME.",
    )
    import_parser.add_argument("--rebuild-fts", action="store_true")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--since")
    search_parser.add_argument("--until")
    search_parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    search_parser.add_argument("--print-md", action="store_true")

    series_parser = subparsers.add_parser("series")
    series_parser.add_argument("--bucket", choices=["hour", "day"], default="day")
    series_parser.add_argument("--since")
    series_parser.add_argument("--until")

    usage_audit_parser = subparsers.add_parser("usage-audit")
    usage_audit_parser.add_argument("--since")
    usage_audit_parser.add_argument(
        "--window-hours",
        type=float,
        default=24.0,
        help="Recent effective usage window when --since is omitted.",
    )
    usage_audit_parser.add_argument(
        "--usage",
        type=Path,
        action="append",
        default=[],
        help="Audit one or more usage JSONL files instead of usage_events in SQLite.",
    )
    usage_audit_parser.add_argument("--print-md", action="store_true")

    subparsers.add_parser("stats")
    subparsers.add_parser("rebuild-fts")

    vector_rebuild_parser = subparsers.add_parser("vector-rebuild")
    vector_rebuild_parser.add_argument("--limit", type=int)

    vector_search_parser = subparsers.add_parser("vector-search")
    vector_search_parser.add_argument("query")
    vector_search_parser.add_argument("--since")
    vector_search_parser.add_argument("--until")
    vector_search_parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)

    metadata_search_parser = subparsers.add_parser("metadata-search")
    metadata_search_parser.add_argument("query")
    metadata_search_parser.add_argument("--since")
    metadata_search_parser.add_argument("--until")
    metadata_search_parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)

    hybrid_search_parser = subparsers.add_parser("hybrid-search")
    hybrid_search_parser.add_argument("query")
    hybrid_search_parser.add_argument("--since")
    hybrid_search_parser.add_argument("--until")
    hybrid_search_parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with connect(args.db) as conn:
        if args.command == "init":
            print(json.dumps(stats(conn), indent=2, sort_keys=True))
            return 0
        if args.command == "import":
            history_paths = list(args.history or [])
            usage_paths = list(args.usage or [])
            session_paths = list(args.session or [])
            if args.state_dir:
                history_paths.extend(discover_history_files(args.state_dir))
                usage_paths.extend(discover_usage_files(args.state_dir))
            for codex_home in args.codex_home or []:
                state_dir = codex_home / "web-bridge"
                history_paths.extend(discover_history_files(state_dir))
                usage_paths.extend(discover_usage_files(state_dir))
                session_paths.extend(discover_session_files(codex_home))
            result = {
                "history": import_history_files(conn, sorted(set(history_paths))),
                "usage": import_usage_files(conn, sorted(set(usage_paths))),
                "session": import_session_files(conn, sorted(set(session_paths))),
            }
            if args.rebuild_fts:
                result["fts"] = rebuild_fts(conn)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command == "search":
            result = search_turns(
                conn,
                query=args.query,
                since=_parse_time(args.since),
                until=_parse_time(args.until),
                limit=args.limit,
            )
            if args.print_md:
                print(render_search_md(result))
            else:
                print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command == "series":
            print(
                json.dumps(
                    time_series(
                        conn,
                        bucket=args.bucket,
                        since=_parse_time(args.since),
                        until=_parse_time(args.until),
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "usage-audit":
            window_seconds = max(0, int(float(args.window_hours or 0) * 3600))
            if args.usage:
                result = usage_audit_from_files(
                    list(args.usage),
                    since_ts=_parse_time(args.since),
                    window_seconds=window_seconds or USAGE_WINDOW_SECONDS,
                )
            else:
                result = usage_audit(
                    conn,
                    since_ts=_parse_time(args.since),
                    window_seconds=window_seconds or USAGE_WINDOW_SECONDS,
                )
            if args.print_md:
                print(render_usage_audit_md(result))
            else:
                print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command == "stats":
            print(json.dumps(stats(conn), indent=2, sort_keys=True))
            return 0
        if args.command == "rebuild-fts":
            print(json.dumps(rebuild_fts(conn), indent=2, sort_keys=True))
            return 0
        if args.command == "vector-rebuild":
            print(
                json.dumps(
                    rebuild_memory_vectors(conn, limit=args.limit),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "vector-search":
            print(
                json.dumps(
                    vector_search(
                        conn,
                        query=args.query,
                        since=_parse_time(args.since),
                        until=_parse_time(args.until),
                        limit=args.limit,
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "metadata-search":
            print(
                json.dumps(
                    metadata_search(
                        conn,
                        query=args.query,
                        since=_parse_time(args.since),
                        until=_parse_time(args.until),
                        limit=args.limit,
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "hybrid-search":
            print(
                json.dumps(
                    hybrid_search(
                        conn,
                        query=args.query,
                        since=_parse_time(args.since),
                        until=_parse_time(args.until),
                        limit=args.limit,
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
