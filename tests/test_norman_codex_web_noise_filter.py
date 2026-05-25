from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_norman_codex_web():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "norman_codex_web.py"
    )
    spec = importlib.util.spec_from_file_location("norman_codex_web", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_strip_codex_transient_stderr_noise_keeps_real_errors() -> None:
    module = _load_norman_codex_web()
    raw = "\n".join(
        [
            "2026-05-01T10:42:40.993706Z ERROR codex_core::tools::router: error=write_stdin failed: stdin closed",
            "2026-05-03T18:03:04.854195Z ERROR codex_core::tools::router: error=apply_patch verification failed: Failed to find expected lines",
            "2026-05-03T18:45:00Z ERROR codex_core::session: failed to record rollout items: thread 019de8e1-dc27-7883-8f2d-3b4753fb9b9a not found",
            "2026-04-27T22:53:57Z ERROR session_loop{thread_id=019dbd24}: codex_core::session: failed to record rollout items: thread 019dbd24-172f-7522-8df6-b3ffcfe7887a not found",
            "2026-05-03T23:29:50.842483Z ERROR codex_models_manager::manager: failed to refresh available models: request timed out",
            "2026-05-09T15:21:37.850188Z ERROR codex_models_manager::manager: failed to refresh available models: timeout waiting for child process to exit",
            "Warning: no last agent message; wrote empty content to /tmp/last_message.txt",
            "real failure",
        ]
    )

    assert module.strip_codex_empty_last_message_warning(raw) == "real failure"


def test_clear_codex_transient_error_history_removes_noise(tmp_path) -> None:
    module = _load_norman_codex_web()
    module.STATE_DIR = tmp_path
    module.HISTORY_PATH = tmp_path / "history.jsonl"

    entries, changed = module.clear_codex_transient_error_history(
        [
            {
                "prompt": "status",
                "response": "[no response returned]",
                "error": "2026-05-01T10:42:40.993706Z ERROR codex_core::tools::router: error=write_stdin failed: stdin closed",
            },
            {
                "prompt": "models",
                "response": "[no response returned]",
                "error": "2026-05-09T15:21:37.850188Z ERROR codex_models_manager::manager: failed to refresh available models: timeout waiting for child process to exit",
            },
            {
                "prompt": "real issue",
                "response": "[no response returned]",
                "error": "real failure",
            },
        ]
    )

    assert changed is True
    assert entries[0]["error"] == ""
    assert entries[1]["error"] == ""
    assert entries[2]["error"] == "real failure"
    assert "write_stdin failed" not in module.HISTORY_PATH.read_text(encoding="utf-8")
    assert "failed to refresh available models" not in module.HISTORY_PATH.read_text(
        encoding="utf-8"
    )
