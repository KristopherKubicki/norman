from __future__ import annotations

import importlib.util
import io
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


def test_vector_preflight_reports_metadata_refs(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    memory_tool = _load_script("tui_memory_tool")
    preflight = _load_script("tui_vector_preflight")
    db = tmp_path / "tui_state.sqlite3"
    session = tmp_path / ".codex-work" / "sessions" / "2026" / "06" / "18" / "s.jsonl"
    _write_jsonl(
        session,
        [
            {
                "timestamp": "2026-06-18T01:02:03Z",
                "type": "session_meta",
                "payload": {"id": "session-preflight"},
            },
            {
                "timestamp": "2026-06-18T01:02:04Z",
                "type": "event_msg",
                "payload": {
                    "type": "task_started",
                    "turn_id": "turn-preflight-1",
                },
            },
            {
                "timestamp": "2026-06-18T01:02:05Z",
                "type": "event_msg",
                "payload": {
                    "type": "user_message",
                    "message": "Panelbot upload handoff failed.",
                },
            },
            {
                "timestamp": "2026-06-18T01:02:06Z",
                "type": "event_msg",
                "payload": {
                    "type": "agent_message",
                    "message": "Callback attachment relay evidence found.",
                },
            },
            {
                "timestamp": "2026-06-18T01:02:07Z",
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "turn_id": "turn-preflight-1",
                },
            },
        ],
    )
    with memory_tool.connect(db) as conn:
        memory_tool.import_session_files(conn, [session])
        memory_tool.rebuild_memory_vectors(conn)

    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_PATH", str(db))
    monkeypatch.setenv("NORMAN_CODEX_VECTOR_PREFLIGHT_LIMIT", "3")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"prompt_preview": "turn-preflight-1"})),
    )

    assert preflight.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["metadata_rows"] == 1
    assert "Metadata memory refs:" in output["summary"]


def test_vector_preflight_empty_prompt_is_noop(monkeypatch, capsys) -> None:
    preflight = _load_script("tui_vector_preflight")
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    assert preflight.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output == {"summary": "", "status": "empty-prompt"}


def test_vector_preflight_missing_db_is_noop(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    preflight = _load_script("tui_vector_preflight")
    missing_db = tmp_path / "missing" / "tui_state.sqlite3"
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_PATH", str(missing_db))
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"prompt_preview": "panelbot callback"})),
    )

    assert preflight.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "missing-db"
    assert output["db"] == str(missing_db)
    assert output["summary"] == ""


def test_vector_preflight_unindexed_db_is_noop(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    memory_tool = _load_script("tui_memory_tool")
    preflight = _load_script("tui_vector_preflight")
    db = tmp_path / "tui_state.sqlite3"
    with memory_tool.connect(db):
        pass
    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_PATH", str(db))
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"prompt_preview": "panelbot callback"})),
    )

    assert preflight.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "unindexed"
    assert output["summary"] == ""
    assert output["memory_vector"]["chunks"] == 0
