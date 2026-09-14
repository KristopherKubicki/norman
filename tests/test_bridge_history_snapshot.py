"""History requests must return full saved turns, independent of status telemetry."""

import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "script", ["norman_codex_web.py", "agent_console_template/agent_console_web.py"]
)
def test_explicit_history_bypasses_stale_truncated_snapshot(
    monkeypatch, tmp_path, script
):
    monkeypatch.setenv("NORMAN_CODEX_WEB_STATE_DIR", str(tmp_path))
    path = Path(__file__).parents[1] / "scripts" / script
    spec = importlib.util.spec_from_file_location("history_snapshot_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module, "status_snapshot", lambda: {"history": [{"response": "old"}]}
    )
    fresh = [{"prompt": "New question", "response": "full reply " * 1000}]
    limits = []

    def saved_history(*, limit):
        limits.append(limit)
        return fresh

    monkeypatch.setattr(module, "load_history", saved_history)
    assert module.requested_status_snapshot({})["history"] == [{"response": "old"}]
    for value, expected in [("40", 40), ("100000", 250), ("-1", 1), ("invalid", 40)]:
        snapshot = module.requested_status_snapshot({"history_limit": [value]})
        assert snapshot["history"] == fresh
        assert limits[-1] == expected
