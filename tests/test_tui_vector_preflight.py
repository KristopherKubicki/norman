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
        expected_turn_id = conn.execute("SELECT id FROM turns").fetchone()["id"]

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
    assert output["memory_ref_ids"] == [expected_turn_id]
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


def test_vector_preflight_schedules_bounded_background_index(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    memory_tool = _load_script("tui_memory_tool")
    preflight = _load_script("tui_vector_preflight")
    db = tmp_path / "tui_state.sqlite3"
    history = tmp_path / "history.jsonl"
    _write_jsonl(
        history,
        [
            {
                "thread_id": "thread-background-index",
                "started_at": 1_780_000_000,
                "prompt": "Index this archive handoff.",
                "response": "The background index should receive this turn.",
            }
        ],
    )
    with memory_tool.connect(db) as conn:
        memory_tool.import_history_files(conn, [history])

    launched: list[list[str]] = []

    class FakeProcess:
        pass

    monkeypatch.setenv("NORMAN_CODEX_STATE_DB_PATH", str(db))
    monkeypatch.setenv("NORMAN_CODEX_VECTOR_INDEX_BATCH", "17")
    monkeypatch.setenv("NORMAN_CODEX_VECTOR_INDEX_BATCHES", "3")
    monkeypatch.setattr(
        preflight.subprocess,
        "Popen",
        lambda args, **_kwargs: launched.append(args) or FakeProcess(),
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"prompt_preview": "archive handoff"})),
    )

    assert preflight.main() == 0
    output = json.loads(capsys.readouterr().out)

    assert output["status"] == "unindexed"
    assert output["indexer"] == {
        "requested": True,
        "status": "scheduled",
        "batch": 17,
        "batches": 3,
        "pending_turns": 1,
    }
    assert launched == [
        [
            sys.executable,
            str(preflight.SCRIPT_DIR / "tui_memory_tool.py"),
            "--db",
            str(db),
            "vector-index",
            "--limit",
            "17",
            "--batches",
            "3",
        ]
    ]


class _RerankResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class _RedactingMemoryTool:
    @staticmethod
    def _redact_memory_text(value):
        return str(value).replace("secret-token", "[REDACTED]"), 1


def _rerank_rows(count: int) -> list[dict]:
    return [
        {
            "turn_id": f"turn-{index}",
            "text_preview": f"archive row {index} secret-token",
        }
        for index in range(count)
    ]


def _rerank_config() -> dict:
    return {
        "enabled": True,
        "endpoint": "https://llm.home.arpa/v1/rerank",
        "model": "BAAI/bge-reranker-v2-m3",
        "timeout_seconds": 4,
        "candidate_limit": 20,
        "verify_tls": True,
    }


def test_rerank_memory_rows_caps_candidates_and_redacts_request(monkeypatch) -> None:
    preflight = _load_script("tui_vector_preflight")
    captured: dict = {}

    def fake_urlopen(request, *, timeout, context):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        captured["context"] = context
        return _RerankResponse(
            {"results": [{"index": index} for index in reversed(range(16))]}
        )

    monkeypatch.setattr(preflight.urllib_request, "urlopen", fake_urlopen)

    receipt = preflight.rerank_memory_rows(
        _RedactingMemoryTool(),
        query="retrieve secret-token routing decision",
        rows=_rerank_rows(20),
        limit=5,
        config=_rerank_config(),
    )

    assert receipt["used"] is True
    assert receipt["status"] == "ok"
    assert receipt["candidate_count"] == 16
    assert receipt["selected_count"] == 5
    assert receipt["memory_ref_ids"] == [
        "turn-15",
        "turn-14",
        "turn-13",
        "turn-12",
        "turn-11",
    ]
    assert captured["timeout"] == 4
    assert captured["context"] is None
    assert len(captured["payload"]["documents"]) == 16
    assert "secret-token" not in json.dumps(captured["payload"])
    assert "[REDACTED]" in json.dumps(captured["payload"])


def test_rerank_memory_rows_falls_back_on_incomplete_ranking(monkeypatch) -> None:
    preflight = _load_script("tui_vector_preflight")
    monkeypatch.setattr(
        preflight.urllib_request,
        "urlopen",
        lambda *_args, **_kwargs: _RerankResponse({"results": [{"index": 1}]}),
    )

    receipt = preflight.rerank_memory_rows(
        _RedactingMemoryTool(),
        query="routing decision",
        rows=_rerank_rows(3),
        limit=2,
        config=_rerank_config(),
    )

    assert receipt["used"] is False
    assert receipt["status"] == "invalid-response"
    assert receipt["failure_class"] == "incomplete-ranking"
    assert receipt["memory_ref_ids"] == ["turn-0", "turn-1"]


def test_rerank_memory_rows_falls_back_on_timeout(monkeypatch) -> None:
    preflight = _load_script("tui_vector_preflight")

    def timeout(*_args, **_kwargs):
        raise TimeoutError("reranker timed out")

    monkeypatch.setattr(preflight.urllib_request, "urlopen", timeout)

    receipt = preflight.rerank_memory_rows(
        _RedactingMemoryTool(),
        query="routing decision",
        rows=_rerank_rows(3),
        limit=2,
        config=_rerank_config(),
    )

    assert receipt["used"] is False
    assert receipt["status"] == "failed"
    assert receipt["failure_class"] == "timeout"
    assert receipt["memory_ref_ids"] == ["turn-0", "turn-1"]
