from __future__ import annotations

import importlib.util
import json
import tempfile
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


def _configure_state(module) -> tempfile.TemporaryDirectory[str]:
    tmp = tempfile.TemporaryDirectory()
    state_dir = Path(tmp.name)
    module.STATE_DIR = state_dir
    module.USAGE_PATH = state_dir / "usage.jsonl"
    module.KPI_PATH = state_dir / "kpis.json"
    return tmp


def test_norman_submit_hands_off_the_composer_before_acknowledgement() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "norman_codex_web.py"
    ).read_text(encoding="utf-8")

    assert "function clearSubmittedComposer() {{" in source
    assert "function restoreRejectedPrompt(draftValue) {{" in source
    assert "clearSubmittedComposer();\n      render(state.snapshot);" in source
    assert "restoreRejectedPrompt(draftValue);" in source
    assert "else if (busy) {{" in source
    assert ".composer-send.pending:disabled" in source
    assert "PROMPT_SUBMISSION_RESTORE_GRACE_MS" not in source


def test_fast_lane_capsule_only_renders_verified_sanitized_outcomes() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "norman_codex_web.py"
    ).read_text(encoding="utf-8")
    helper = source.split("function fastLaneOutcomeCapsuleState(snapshot) {{", 1)[
        1
    ].split("function buildStatusCapsules", 1)[0]

    assert 'String(outcome.state || "").trim().toLowerCase() === "verified"' in helper
    assert 'laneKind === "luna" || laneKind === "local"' in helper
    assert "Estimated, not invoiced" in helper
    assert "Latest route is not counted as a win" in helper
    assert "automatic route selection remains off" in helper
    for forbidden in (
        "selected_worker",
        "observed_worker",
        "target_worker",
        "peer_path",
        "frontdoor",
        "endpoint",
        "spark-",
    ):
        assert forbidden not in helper


def test_build_kpi_snapshot_marks_prompt_with_node_warning_degraded() -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    try:
        snapshot = module.build_kpi_snapshot(
            {
                "pending": False,
                "pane": """
⚠ Disabled `js_repl` for this session because the configured Node runtime is
  unavailable or incompatible. Node runtime too old for js_repl.

› Use /skills to list available skills

  gpt-5.5 xhigh fast · /home/debian/networking
""",
                "usage": {"totals": {}},
                "services": [],
                "auth": {"required": False},
            },
            previous={},
        )

        assert snapshot["state"] == "degraded"
        assert snapshot["activity_state"] == "idle"
        assert snapshot["prompt_visible"] is True
        assert snapshot["signals"][0]["code"] == "js_repl_node_too_old"
    finally:
        tmp.cleanup()


def test_build_kpi_snapshot_ignores_optional_inactive_service() -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    try:
        snapshot = module.build_kpi_snapshot(
            {
                "pending": False,
                "pane": "› ready",
                "usage": {"totals": {}},
                "services": [
                    {
                        "name": "tailscaled.service",
                        "state": "inactive",
                        "required": False,
                    }
                ],
                "auth": {"required": False},
            },
            previous={},
        )

        assert snapshot["state"] == "idle"
        assert snapshot["health_state"] == "ok"
        assert "service_not_active" not in {
            item["code"] for item in snapshot["signals"]
        }
    finally:
        tmp.cleanup()


def test_build_kpi_snapshot_marks_stale_non_prompt_as_wedged() -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    original_now = module.now_ts
    original_wedge_seconds = module.KPI_WEDGE_SECONDS
    try:
        module.now_ts = lambda: 1000
        module.KPI_WEDGE_SECONDS = 300
        pane = "still running without a prompt"
        snapshot = module.build_kpi_snapshot(
            {
                "pending": False,
                "pane": pane,
                "usage": {"totals": {}},
                "services": [],
                "auth": {"required": False},
            },
            previous={
                "state": "working",
                "last_pane_hash": module._pane_hash(pane),
                "last_output_changed_at": 100,
                "metrics": {"wedge_count": 0, "state_changes": 0},
            },
        )

        assert snapshot["state"] == "wedged"
        assert snapshot["stale_seconds"] == 900
        assert snapshot["metrics"]["wedge_count"] == 1
    finally:
        module.now_ts = original_now
        module.KPI_WEDGE_SECONDS = original_wedge_seconds
        tmp.cleanup()


def test_build_kpi_snapshot_marks_running_no_output_degraded_not_wedged() -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    original_now = module.now_ts
    original_wedge_seconds = module.KPI_WEDGE_SECONDS
    original_running_no_output = module.RUNNING_NO_OUTPUT_SECONDS
    try:
        module.now_ts = lambda: 1000
        module.KPI_WEDGE_SECONDS = 300
        module.RUNNING_NO_OUTPUT_SECONDS = 600
        pane = "model process active but visually unchanged"
        snapshot = module.build_kpi_snapshot(
            {
                "pending": True,
                "model_process_alive": True,
                "web_worker_alive": True,
                "last_started_at": 200,
                "pane": pane,
                "usage": {"totals": {}},
                "services": [],
                "auth": {"required": False},
            },
            previous={
                "state": "working",
                "last_pane_hash": module._pane_hash(pane),
                "last_output_changed_at": 100,
                "metrics": {
                    "wedge_count": 0,
                    "degraded_count": 0,
                    "state_changes": 0,
                },
            },
        )

        assert snapshot["state"] == "degraded"
        assert snapshot["activity_state"] == "working"
        assert snapshot["health_state"] == "degraded"
        assert snapshot["stale_seconds"] == 900
        assert snapshot["metrics"]["pending_seconds"] == 800
        assert snapshot["metrics"]["wedge_count"] == 0
        assert snapshot["metrics"]["degraded_count"] == 1
        assert snapshot["signals"][0]["code"] == "running_no_output"
    finally:
        module.now_ts = original_now
        module.KPI_WEDGE_SECONDS = original_wedge_seconds
        module.RUNNING_NO_OUTPUT_SECONDS = original_running_no_output
        tmp.cleanup()


def test_build_kpi_snapshot_marks_auth_required_as_blocked() -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    try:
        snapshot = module.build_kpi_snapshot(
            {
                "pending": False,
                "pane": "Complete device-code sign-in.",
                "usage": {"totals": {}},
                "services": [],
                "auth": {"required": True},
            },
            previous={},
        )

        assert snapshot["state"] == "blocked"
        assert snapshot["health_state"] == "blocked"
        assert snapshot["signals"][0]["code"] == "auth_required"
    finally:
        tmp.cleanup()


def test_build_kpi_snapshot_marks_latest_usage_limit_failure_blocked() -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    try:
        latest_error = "You've hit your usage limit. Try again at 5:28 PM."
        assert (
            module._current_usage_limit_error_text(
                {
                    "last_error": "",
                    "history": [
                        {"error": "", "started_at": 10, "finished_at": 20},
                        {
                            "error": latest_error,
                            "started_at": 30,
                            "finished_at": 40,
                        },
                    ],
                },
                "",
            )
            == latest_error
        )
        snapshot = module.build_kpi_snapshot(
            {
                "pending": False,
                "state": "ok",
                "last_error": "",
                "pane": "› ready",
                "usage": {"totals": {}},
                "services": [],
                "auth": {"required": False},
                "history": [
                    {
                        "error": "",
                        "started_at": 10,
                        "finished_at": 20,
                    },
                    {
                        "error": "You've hit your usage limit. Try again at 5:28 PM.",
                        "started_at": 30,
                        "finished_at": 40,
                    },
                ],
            },
            previous={},
        )

        assert snapshot["state"] == "blocked"
        assert snapshot["health_state"] == "blocked"
        assert snapshot["signals"][0]["code"] == "usage_limit"
    finally:
        tmp.cleanup()


def test_build_kpi_snapshot_ignores_stale_usage_limit_after_success() -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    try:
        assert (
            module._current_usage_limit_error_text(
                {
                    "last_error": "",
                    "state": "ok",
                    "history": [
                        {
                            "error": "You've hit your usage limit. Try again at 5:28 PM.",
                            "started_at": 10,
                            "finished_at": 20,
                        },
                        {
                            "error": "",
                            "service_tier": "bedrock-failover",
                            "started_at": 30,
                            "finished_at": 40,
                        },
                    ],
                },
                "old output: You've hit your usage limit. Try again at 5:28 PM.",
            )
            == ""
        )
        snapshot = module.build_kpi_snapshot(
            {
                "pending": False,
                "state": "ok",
                "last_error": "",
                "pane": (
                    "old output: You've hit your usage limit. "
                    "Try again at 5:28 PM.\n› ready"
                ),
                "usage": {"totals": {}},
                "services": [],
                "auth": {"required": False},
                "history": [
                    {
                        "error": "You've hit your usage limit. Try again at 5:28 PM.",
                        "started_at": 10,
                        "finished_at": 20,
                    },
                    {
                        "error": "",
                        "service_tier": "bedrock-failover",
                        "started_at": 30,
                        "finished_at": 40,
                    },
                ],
            },
            previous={},
        )

        assert "usage_limit" not in {
            str(item.get("code") or "") for item in snapshot["signals"]
        }
        assert snapshot["state"] != "blocked"
    finally:
        tmp.cleanup()


def _kaizen_snapshot_fixture() -> dict:
    return {
        "kpis": {
            "observed_at": 1_786_000_000,
            "state": "idle",
            "activity_state": "idle",
            "health_state": "ok",
            "prompt_visible": False,
            "waiting_visible": False,
            "state_entered_at": 1_785_999_000,
            "metrics": {
                "turns": 12,
                "successful_turns": 10,
                "failed_turns": 2,
                "avg_turn_seconds": 20,
                "last_turn_at": 1_786_000_000,
                "pending_seconds": 0,
                "queue_depth": 0,
                "wedge_count": 0,
                "blocked_count": 0,
                "degraded_count": 0,
                "state_changes": 3,
                "forbidden_metric": 99,
            },
        }
    }


def test_kaizen_tui_payload_is_strict_and_sanitized(monkeypatch) -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    try:
        monkeypatch.setenv("NORMAN_KAIZEN_REALM", "personal/home")
        monkeypatch.setenv("NORMAN_KAIZEN_SOURCE_TUI", "pilot alpha !")

        payload = module.build_kaizen_tui_snapshot_payload(_kaizen_snapshot_fixture())

        assert payload is not None
        assert set(payload) == {
            "schema",
            "realm",
            "source_tui",
            "observed_at",
            "state",
            "activity_state",
            "health_state",
            "prompt_visible",
            "waiting_visible",
            "state_entered_at",
            "metrics",
        }
        assert payload["source_tui"] == "pilot-alpha"
        assert payload["observed_at"].endswith("+00:00")
        assert payload["state_entered_at"].endswith("+00:00")
        assert set(payload["metrics"]) == set(module._KAIZEN_METRIC_LIMITS)
        assert "forbidden_metric" not in payload["metrics"]
    finally:
        tmp.cleanup()


def test_kaizen_tui_emitter_is_disabled_by_default(monkeypatch) -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    try:
        monkeypatch.delenv("NORMAN_KAIZEN_ENABLED", raising=False)
        calls = []
        monkeypatch.setattr(
            module.urllib_request,
            "urlopen",
            lambda *args, **kwargs: calls.append((args, kwargs)),
        )

        assert module.emit_kaizen_tui_snapshot(_kaizen_snapshot_fixture()) is False
        assert calls == []
    finally:
        tmp.cleanup()


def test_kaizen_tui_emitter_posts_bearer_payload_and_swallows_errors(
    monkeypatch,
) -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    try:
        monkeypatch.setenv("NORMAN_KAIZEN_ENABLED", "1")
        monkeypatch.setenv(
            "NORMAN_CONSOLE_RUNTIME_API_BASE",
            "http://norman.test/api/v1/console-runtime",
        )
        monkeypatch.setenv("NORMAN_CONSOLE_RUNTIME_TOKEN", "test-token")
        calls = []

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b"{}"

        def _urlopen(request, timeout):
            calls.append((request, timeout))
            return _Response()

        monkeypatch.setattr(module.urllib_request, "urlopen", _urlopen)

        assert module.emit_kaizen_tui_snapshot(_kaizen_snapshot_fixture()) is True
        request, timeout = calls[0]
        assert request.full_url == "http://norman.test/api/v1/kaizen/tui-snapshots"
        assert request.get_header("Authorization") == "Bearer test-token"
        assert timeout == module._kaizen_emit_timeout_seconds()
        assert json.loads(request.data.decode("utf-8")) == (
            module.build_kaizen_tui_snapshot_payload(_kaizen_snapshot_fixture())
        )

        monkeypatch.setattr(
            module.urllib_request,
            "urlopen",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")),
        )
        assert module.emit_kaizen_tui_snapshot(_kaizen_snapshot_fixture()) is False
    finally:
        tmp.cleanup()


def test_kaizen_tui_snapshot_url_only_strips_console_runtime_path_segment(
    monkeypatch,
) -> None:
    module = _load_norman_codex_web()
    monkeypatch.setenv(
        "NORMAN_CONSOLE_RUNTIME_API_BASE",
        "http://norman.test/api/v1/not-console-runtime",
    )

    assert (
        module._kaizen_tui_snapshot_url()
        == "http://norman.test/api/v1/not-console-runtime/api/v1/kaizen/tui-snapshots"
    )
