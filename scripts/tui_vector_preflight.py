#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.parse
from urllib import error as urllib_error
from urllib import request as urllib_request
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_LIMIT = 5
DEFAULT_INDEX_BATCH = 128
DEFAULT_INDEX_BATCHES = 8
DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
DEFAULT_RERANK_CANDIDATES = 8
DEFAULT_RERANK_TIMEOUT_SECONDS = 8
DEFAULT_RERANK_DOCUMENT_CHARS = 1200
DEFAULT_RERANK_QUERY_CHARS = 1200


def _load_memory_tool() -> Any:
    path = SCRIPT_DIR / "tui_memory_tool.py"
    spec = importlib.util.spec_from_file_location("tui_memory_tool", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _state_db_path() -> Path:
    explicit = os.environ.get("NORMAN_CODEX_STATE_DB_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    state_dir = os.environ.get("NORMAN_CODEX_WEB_STATE_DIR", "").strip()
    if state_dir:
        return Path(state_dir).expanduser() / "tui_state.sqlite3"
    codex_home = os.environ.get("CODEX_HOME", "").strip()
    if codex_home:
        return Path(codex_home).expanduser() / "web-bridge" / "tui_state.sqlite3"
    return Path.home() / ".codex" / "web-bridge" / "tui_state.sqlite3"


def _preview(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def _row_summary(row: dict[str, Any]) -> str:
    started = row.get("started_at") or ""
    thread = str(row.get("thread_id") or "")[:12]
    kind = str(row.get("chunk_kind") or "turn")
    text = _preview(row.get("text_preview") or row.get("response_preview") or row)
    return f"{started} {thread} {kind}: {text}".strip()


def _summary(result: dict[str, Any], rerank: dict[str, Any] | None = None) -> str:
    vector_rows = result.get("vector", {}).get("rows", [])
    metadata_rows = result.get("metadata", {}).get("rows", [])
    fts_rows = result.get("fts", {}).get("rows", [])
    lines = []
    if vector_rows:
        lines.append("Vector memory refs:")
        lines.extend(f"- {_row_summary(row)}" for row in vector_rows[:DEFAULT_LIMIT])
    if metadata_rows:
        lines.append("Metadata memory refs:")
        lines.extend(f"- {_row_summary(row)}" for row in metadata_rows[:DEFAULT_LIMIT])
    if fts_rows:
        lines.append("FTS memory refs:")
        lines.extend(f"- {_row_summary(row)}" for row in fts_rows[:DEFAULT_LIMIT])
    if isinstance(rerank, dict) and rerank.get("used"):
        lines.append(
            "Local Spark rerank selected "
            f"{int(rerank.get('selected_count') or 0)} of "
            f"{int(rerank.get('candidate_count') or 0)} archive candidates."
        )
    return "\n".join(lines)


def _memory_ref_ids(result: dict[str, Any], *, limit: int) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for source in ("vector", "metadata", "fts"):
        rows = result.get(source, {}).get("rows", [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            turn_id = str(row.get("turn_id") or row.get("id") or "").strip()
            if not turn_id or turn_id in seen:
                continue
            seen.add(turn_id)
            selected.append(turn_id)
            if len(selected) >= limit:
                return selected
    return selected


def _memory_rows(result: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in ("vector", "metadata", "fts"):
        rows = result.get(source, {}).get("rows", [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            turn_id = str(row.get("turn_id") or row.get("id") or "").strip()
            if not turn_id or turn_id in seen:
                continue
            seen.add(turn_id)
            selected.append(dict(row))
            if len(selected) >= limit:
                return selected
    return selected


def _truthy_env(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _bounded_env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _rerank_config() -> dict[str, Any]:
    endpoint = os.environ.get("NORMAN_CODEX_VECTOR_RERANK_URL", "").strip()
    return {
        "enabled": _truthy_env("NORMAN_CODEX_VECTOR_RERANK_ENABLED", "0"),
        "endpoint": endpoint,
        "model": (
            os.environ.get(
                "NORMAN_CODEX_VECTOR_RERANK_MODEL", DEFAULT_RERANK_MODEL
            ).strip()
            or DEFAULT_RERANK_MODEL
        ),
        "timeout_seconds": _bounded_env_int(
            "NORMAN_CODEX_VECTOR_RERANK_TIMEOUT_SECONDS",
            DEFAULT_RERANK_TIMEOUT_SECONDS,
            minimum=1,
            maximum=60,
        ),
        "candidate_limit": _bounded_env_int(
            "NORMAN_CODEX_VECTOR_RERANK_CANDIDATES",
            DEFAULT_RERANK_CANDIDATES,
            minimum=1,
            maximum=16,
        ),
        "verify_tls": _truthy_env("NORMAN_CODEX_VECTOR_RERANK_VERIFY_TLS", "1"),
    }


def _safe_endpoint(value: Any) -> str:
    try:
        parsed = urllib.parse.urlsplit(str(value or "").strip())
    except ValueError:
        return ""
    if not parsed.scheme or not parsed.hostname:
        return ""
    host = parsed.hostname
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _sanitize_rerank_text(memory_tool: Any, value: Any, *, limit: int) -> str:
    raw = str(value or "")
    redactor = getattr(memory_tool, "_redact_memory_text", None)
    if callable(redactor):
        try:
            raw, _redactions = redactor(raw)
        except Exception:
            pass
    clean = " ".join(str(raw or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)] + "..."


def _rerank_document(memory_tool: Any, row: dict[str, Any]) -> str:
    parts = [
        row.get("text_preview"),
        row.get("prompt_preview"),
        row.get("response_preview"),
        row.get("error_preview"),
    ]
    text = "\n".join(str(part or "") for part in parts if str(part or "").strip())
    return _sanitize_rerank_text(memory_tool, text, limit=DEFAULT_RERANK_DOCUMENT_CHARS)


def _rerank_failure_class(exc: BaseException) -> str:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, urllib_error.HTTPError):
        return f"http-{int(exc.code)}"
    if isinstance(exc, urllib_error.URLError):
        return "transport"
    return type(exc).__name__.lower()


def rerank_memory_rows(
    memory_tool: Any,
    *,
    query: str,
    rows: list[dict[str, Any]],
    limit: int,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = dict(config or _rerank_config())
    try:
        candidate_limit = int(
            settings.get("candidate_limit", DEFAULT_RERANK_CANDIDATES)
        )
    except (TypeError, ValueError):
        candidate_limit = DEFAULT_RERANK_CANDIDATES
    candidate_limit = max(1, min(16, candidate_limit))
    requested_limit = max(0, min(candidate_limit, int(limit)))
    candidate_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        turn_id = str(row.get("turn_id") or row.get("id") or "").strip()
        if not turn_id or turn_id in seen:
            continue
        document = _rerank_document(memory_tool, row)
        if not document:
            continue
        seen.add(turn_id)
        candidate_rows.append({"turn_id": turn_id, "document": document})
        if len(candidate_rows) >= candidate_limit:
            break
    baseline_ids = [item["turn_id"] for item in candidate_rows[:requested_limit]]
    endpoint = _safe_endpoint(settings.get("endpoint"))
    receipt: dict[str, Any] = {
        "schema": "norman.tui.memory-rerank-receipt.v1",
        "configured": bool(settings.get("enabled") and endpoint),
        "used": False,
        "status": "disabled",
        "model": str(settings.get("model") or "").strip(),
        "endpoint": endpoint,
        "candidate_count": len(candidate_rows),
        "selected_count": len(baseline_ids),
        "failure_class": "",
        "latency_ms": 0,
    }
    if not settings.get("enabled"):
        return {**receipt, "memory_ref_ids": baseline_ids}
    if not endpoint:
        return {
            **receipt,
            "status": "unconfigured",
            "failure_class": "missing-endpoint",
            "memory_ref_ids": baseline_ids,
        }
    if not candidate_rows:
        return {
            **receipt,
            "status": "no-candidates",
            "memory_ref_ids": baseline_ids,
        }

    clean_query = _sanitize_rerank_text(
        memory_tool, query, limit=DEFAULT_RERANK_QUERY_CHARS
    )
    if not clean_query:
        return {
            **receipt,
            "status": "empty-query",
            "failure_class": "empty-query",
            "memory_ref_ids": baseline_ids,
        }
    started = time.monotonic()
    request = urllib_request.Request(
        endpoint,
        data=json.dumps(
            {
                "model": receipt["model"],
                "query": clean_query,
                "documents": [item["document"] for item in candidate_rows],
                "top_n": len(candidate_rows),
            }
        ).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "norman-tui-vector-preflight/1.0",
        },
    )
    context = (
        None if settings.get("verify_tls") else ssl._create_unverified_context()  # nosec B323 - explicit local opt-out
    )
    try:
        with urllib_request.urlopen(
            request,
            timeout=float(settings.get("timeout_seconds") or 1),
            context=context,
        ) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (
        TimeoutError,
        socket.timeout,
        urllib_error.HTTPError,
        urllib_error.URLError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        return {
            **receipt,
            "status": "failed",
            "failure_class": _rerank_failure_class(exc),
            "latency_ms": int((time.monotonic() - started) * 1000),
            "memory_ref_ids": baseline_ids,
        }
    if not isinstance(payload, dict):
        return {
            **receipt,
            "status": "invalid-response",
            "failure_class": "non-object-response",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "memory_ref_ids": baseline_ids,
        }

    results = payload.get("results")
    indexes: list[int] = []
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, dict):
                continue
            try:
                index = int(result.get("index"))
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(candidate_rows) and index not in indexes:
                indexes.append(index)
    if len(indexes) != len(candidate_rows):
        return {
            **receipt,
            "status": "invalid-response",
            "failure_class": "incomplete-ranking",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "memory_ref_ids": baseline_ids,
        }
    selected_ids = [
        candidate_rows[index]["turn_id"] for index in indexes[:requested_limit]
    ]
    return {
        **receipt,
        "used": True,
        "status": "ok",
        "model": str(payload.get("model") or receipt["model"]).strip()
        or receipt["model"],
        "selected_count": len(selected_ids),
        "failure_class": "ok",
        "latency_ms": int((time.monotonic() - started) * 1000),
        "memory_ref_ids": selected_ids,
        "score_method": str(
            (
                payload.get("norllama", {}).get("score_method")
                if isinstance(payload.get("norllama"), dict)
                else payload.get("score_method")
            )
            or ""
        ).strip(),
    }


def _index_batch_size() -> int:
    try:
        return max(
            1,
            int(
                os.environ.get(
                    "NORMAN_CODEX_VECTOR_INDEX_BATCH",
                    str(DEFAULT_INDEX_BATCH),
                )
            ),
        )
    except ValueError:
        return DEFAULT_INDEX_BATCH


def _index_batch_count() -> int:
    try:
        return max(
            1,
            int(
                os.environ.get(
                    "NORMAN_CODEX_VECTOR_INDEX_BATCHES",
                    str(DEFAULT_INDEX_BATCHES),
                )
            ),
        )
    except ValueError:
        return DEFAULT_INDEX_BATCHES


def _request_background_index(
    db_path: Path,
    *,
    pending_turns: int,
) -> dict[str, Any]:
    if pending_turns <= 0:
        return {"requested": False, "status": "current"}
    memory_tool_path = SCRIPT_DIR / "tui_memory_tool.py"
    if not memory_tool_path.is_file():
        return {"requested": False, "status": "missing-memory-tool"}
    batch = _index_batch_size()
    batches = _index_batch_count()
    try:
        subprocess.Popen(
            [
                sys.executable,
                str(memory_tool_path),
                "--db",
                str(db_path),
                "vector-index",
                "--limit",
                str(batch),
                "--batches",
                str(batches),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        return {
            "requested": False,
            "status": f"spawn-error:{type(exc).__name__}",
        }
    return {
        "requested": True,
        "status": "scheduled",
        "batch": batch,
        "batches": batches,
        "pending_turns": pending_turns,
    }


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    prompt = str(payload.get("prompt_preview") or "").strip()
    if not prompt:
        print(json.dumps({"summary": "", "status": "empty-prompt"}))
        return 0

    limit = _bounded_env_int(
        "NORMAN_CODEX_VECTOR_PREFLIGHT_LIMIT",
        DEFAULT_LIMIT,
        minimum=1,
        maximum=32,
    )
    db_path = _state_db_path()
    if not db_path.exists():
        print(
            json.dumps(
                {
                    "summary": "",
                    "status": "missing-db",
                    "db": str(db_path),
                },
                sort_keys=True,
            )
        )
        return 0

    memory_tool = _load_memory_tool()
    with memory_tool.connect(db_path) as conn:
        stats = memory_tool.stats(conn)
        vector_stats = stats.get("memory_vector") or {}
        indexer = _request_background_index(
            db_path,
            pending_turns=int(vector_stats.get("pending_turns") or 0),
        )
        if int(vector_stats.get("chunks") or 0) <= 0:
            print(
                json.dumps(
                    {
                        "summary": "",
                        "status": "unindexed",
                        "db": str(db_path),
                        "memory_vector": vector_stats,
                        "indexer": indexer,
                    },
                    sort_keys=True,
                )
            )
            return 0
        rerank_config = _rerank_config()
        candidate_limit = max(limit, int(rerank_config["candidate_limit"]))
        result = memory_tool.hybrid_search(conn, query=prompt, limit=candidate_limit)

    candidate_rows = _memory_rows(result, limit=candidate_limit)
    baseline_memory_ref_ids = [
        str(row.get("turn_id") or row.get("id") or "").strip()
        for row in candidate_rows[:limit]
        if str(row.get("turn_id") or row.get("id") or "").strip()
    ]
    rerank = rerank_memory_rows(
        memory_tool,
        query=prompt,
        rows=candidate_rows,
        limit=limit,
        config=rerank_config,
    )

    print(
        json.dumps(
            {
                "summary": _summary(result, rerank),
                "status": "ok",
                "db": str(db_path),
                "vector_rows": len(result.get("vector", {}).get("rows", [])),
                "metadata_rows": len(result.get("metadata", {}).get("rows", [])),
                "fts_rows": len(result.get("fts", {}).get("rows", [])),
                "memory_candidate_count": len(candidate_rows),
                "baseline_memory_ref_ids": baseline_memory_ref_ids,
                "memory_ref_ids": rerank.get("memory_ref_ids")
                or _memory_ref_ids(result, limit=limit),
                "rerank": rerank,
                "indexer": indexer,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
