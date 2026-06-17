from __future__ import annotations

import importlib.util
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
