#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_LIMIT = 5


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


def _summary(result: dict[str, Any]) -> str:
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
    return "\n".join(lines)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    prompt = str(payload.get("prompt_preview") or "").strip()
    if not prompt:
        print(json.dumps({"summary": "", "status": "empty-prompt"}))
        return 0

    limit = int(os.environ.get("NORMAN_CODEX_VECTOR_PREFLIGHT_LIMIT", DEFAULT_LIMIT))
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
        if int(vector_stats.get("chunks") or 0) <= 0:
            print(
                json.dumps(
                    {
                        "summary": "",
                        "status": "unindexed",
                        "db": str(db_path),
                        "memory_vector": vector_stats,
                    },
                    sort_keys=True,
                )
            )
            return 0
        result = memory_tool.hybrid_search(conn, query=prompt, limit=limit)

    print(
        json.dumps(
            {
                "summary": _summary(result),
                "status": "ok",
                "db": str(db_path),
                "vector_rows": len(result.get("vector", {}).get("rows", [])),
                "metadata_rows": len(result.get("metadata", {}).get("rows", [])),
                "fts_rows": len(result.get("fts", {}).get("rows", [])),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
