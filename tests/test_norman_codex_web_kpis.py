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
    module.KPI_DGX_RANKING_PATH = state_dir / "kpi_dgx_ranking.json"
    module.KPI_APP_HEALTH_PATH = state_dir / "kpi_app_health.json"
    module.KPI_INFRA_HEALTH_PATH = state_dir / "kpi_infra_health.json"
    return tmp


def test_web_app_health_is_pinned_for_every_console(monkeypatch) -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    try:
        monkeypatch.setattr(module, "AGENT_SLUG", "scout")
        module.write_json(
            module.KPI_APP_HEALTH_PATH,
            {
                "checked_at": module.now_ts(),
                "components": [
                    {
                        "id": "engine",
                        "label": "engine",
                        "required": True,
                        "ok": True,
                        "latency_ms": 4,
                    },
                    {
                        "id": "route",
                        "label": "route",
                        "required": True,
                        "ok": True,
                        "latency_ms": 18,
                    },
                ],
            },
        )
        candidates = module.build_local_kpi_candidates(
            {"services": [], "bbs": {"counts": {}}}, {}, observed_at=module.now_ts()
        )
        top, _ = module.top_kpi_meters(candidates)

        assert top[0]["id"] == "app-health"
        assert top[0]["value"] == "2/2 up"
        assert top[0]["tone"] == "ok"
        assert top[0]["source"] == "local app probes"
        assert (
            next(item for item in candidates if item["id"] == "app-latency")["value"]
            == "18ms"
        )
    finally:
        tmp.cleanup()


def test_web_app_health_alerts_when_required_attachment_is_down(monkeypatch) -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    try:
        monkeypatch.setattr(module, "AGENT_SLUG", "panelbot")
        module.write_json(
            module.KPI_APP_HEALTH_PATH,
            {
                "checked_at": module.now_ts(),
                "components": [
                    {
                        "id": "engine",
                        "label": "engine",
                        "required": True,
                        "ok": True,
                        "latency_ms": 3,
                    },
                    {
                        "id": "attached-1",
                        "label": "dashboard",
                        "required": True,
                        "ok": False,
                        "latency_ms": 2001,
                    },
                ],
            },
        )
        meter = module.app_health_kpi_meters()[0]

        assert meter["value"] == "1/2 up"
        assert meter["tone"] == "alert"
        assert meter["detail"] == "Unavailable: dashboard"
    finally:
        tmp.cleanup()


def test_web_app_health_handles_absent_stale_and_optional_components(
    monkeypatch,
) -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    try:
        monkeypatch.setattr(module, "AGENT_SLUG", "studio")
        assert module.app_health_kpi_meters() == []

        checked_at = module.now_ts() - (module.KPI_DGX_REFRESH_SECONDS * 3)
        module.write_json(
            module.KPI_APP_HEALTH_PATH,
            {
                "checked_at": checked_at,
                "components": [
                    {
                        "id": "engine",
                        "label": "engine",
                        "required": True,
                        "ok": True,
                        "latency_ms": 7,
                    },
                    {
                        "id": "attached-1",
                        "label": "preview",
                        "required": False,
                        "ok": False,
                        "latency_ms": 12,
                    },
                ],
            },
        )
        meter = module.app_health_kpi_meters()[0]

        assert meter["tone"] == "warn"
        assert meter["updated_at"] == checked_at
        assert meter["stale_after_seconds"] < module.now_ts() - checked_at
        assert meter["detail"] == "Unavailable: preview"
    finally:
        tmp.cleanup()


def test_app_health_cache_does_not_persist_probe_urls_or_tokens(monkeypatch) -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    try:
        monkeypatch.setattr(
            module,
            "configured_kpi_app_probes",
            lambda: [
                {
                    "id": "engine",
                    "label": "engine",
                    "url": "http://127.0.0.1/health?token=very-secret",
                    "required": True,
                }
            ],
        )
        monkeypatch.setattr(
            module,
            "_probe_kpi_app_component",
            lambda target: {
                "id": target["id"],
                "label": target["label"],
                "required": True,
                "ok": True,
                "status": "ok",
                "http_status": 200,
                "latency_ms": 1,
            },
        )
        module.refresh_kpi_app_health()
        serialized = module.KPI_APP_HEALTH_PATH.read_text(encoding="utf-8")

        assert "very-secret" not in serialized
        assert '"url"' not in serialized
    finally:
        tmp.cleanup()


def test_app_probe_retries_one_transport_failure(monkeypatch) -> None:
    module = _load_norman_codex_web()
    outcomes = iter(
        [
            (False, "unreachable", 0),
            (True, "ok", 200),
        ]
    )
    monkeypatch.setattr(
        module, "_request_kpi_app_component", lambda _target: next(outcomes)
    )

    component = module._probe_kpi_app_component(
        {"id": "engine", "label": "engine", "required": True}
    )

    assert component["ok"] is True
    assert component["status"] == "ok"
    assert component["http_status"] == 200


def test_degraded_app_health_rechecks_faster_than_healthy_health(monkeypatch) -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    started: list[bool] = []

    class FakeThread:
        def __init__(self, **_kwargs):
            pass

        def start(self) -> None:
            started.append(True)

    try:
        monkeypatch.setattr(module.threading, "Thread", FakeThread)
        checked_at = module.now_ts() - 31
        module.write_json(
            module.KPI_APP_HEALTH_PATH,
            {
                "checked_at": checked_at,
                "components": [{"required": True, "ok": False}],
            },
        )

        assert module.maybe_schedule_kpi_app_health() is True
        assert started == [True]

        module.KPI_APP_REFRESH_ACTIVE = False
        module.write_json(
            module.KPI_APP_HEALTH_PATH,
            {
                "checked_at": checked_at,
                "components": [{"required": True, "ok": True}],
            },
        )
        assert module.maybe_schedule_kpi_app_health() is False
    finally:
        module.KPI_APP_REFRESH_ACTIVE = False
        tmp.cleanup()


def test_norman_pins_local_compute_and_network_health(monkeypatch) -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    try:
        monkeypatch.setattr(module, "AGENT_SLUG", "norman")
        module.write_json(
            module.KPI_INFRA_HEALTH_PATH,
            {
                "checked_at": module.now_ts(),
                "nodes": [
                    {"id": "spark-150", "role": "DGX", "ok": True},
                    {"id": "spark-151", "role": "DGX", "ok": True},
                    {"id": "mac-mini", "role": "fallback", "ok": True},
                    {"id": "norllama-frontdoor", "role": "network", "ok": True},
                ],
            },
        )
        candidates = module.build_local_kpi_candidates(
            {"services": [], "bbs": {"counts": {}}}, {}, observed_at=module.now_ts()
        )
        top, _ = module.top_kpi_meters(candidates)

        assert [item["id"] for item in top[:3]] == [
            "infra-dgx",
            "infra-mac",
            "infra-network",
        ]
        assert [item["value"] for item in top[:3]] == ["2/2 up", "Up", "Good"]
        assert all(item["source"].startswith("local") for item in top[:3])
    finally:
        tmp.cleanup()


def test_norman_infra_health_does_not_report_unknown_as_healthy(monkeypatch) -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    try:
        monkeypatch.setattr(module, "AGENT_SLUG", "norman")
        module.write_json(
            module.KPI_INFRA_HEALTH_PATH,
            {
                "checked_at": module.now_ts(),
                "nodes": [
                    {"id": "spark-150", "role": "DGX", "ok": True},
                    {"id": "spark-151", "role": "DGX", "ok": False},
                    {"id": "mac-mini", "role": "fallback", "ok": False},
                    {"id": "norllama-frontdoor", "role": "network", "ok": True},
                ],
            },
        )
        meters = {item["id"]: item for item in module.norman_infra_kpi_meters()}

        assert meters["infra-dgx"]["value"] == "1/2 up"
        assert meters["infra-dgx"]["tone"] == "alert"
        assert meters["infra-mac"]["value"] == "Down"
        assert meters["infra-network"]["value"] == "Issue"
        assert "spark-151" in meters["infra-network"]["detail"]
    finally:
        tmp.cleanup()


def test_top_kpis_use_domain_meter_and_local_dgx_ranking(monkeypatch) -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    try:
        monkeypatch.setattr(module, "AGENT_SLUG", "scout")
        ranked_at = module.now_ts()
        module.write_json(
            module.KPI_DGX_RANKING_PATH,
            {
                "ranked_at": ranked_at,
                "status": "ranked",
                "model": "qwen3.8:27b",
                "selected_ids": ["pp_blocked", "queue", "health", "local-share"],
                "cloud_fallback": False,
            },
        )
        snapshot = module.build_kpi_snapshot(
            {
                "pending": False,
                "pane": "› ready",
                "usage": {"totals": {}, "route_utilization": {"last_24h": {}}},
                "services": [{"name": "scout.service", "state": "active"}],
                "auth": {"required": False},
                "resource_meter": {
                    "kpi_meters": [
                        {
                            "id": "pp_blocked",
                            "label": "PP Blocked",
                            "value": 3,
                            "tone": "danger",
                            "source": "local scout artifact",
                        }
                    ]
                },
                "bbs": {"counts": {}},
            },
            previous={},
        )

        assert snapshot["profile"] == "research"
        assert [item["id"] for item in snapshot["top_meters"]] == [
            "pp_blocked",
            "queue",
            "health",
            "local-share",
        ]
        assert snapshot["processor"] == {
            "mode": "local-dgx",
            "status": "ranked",
            "model": "qwen3.8:27b",
            "ranked_at": ranked_at,
            "cloud_fallback": False,
        }
    finally:
        tmp.cleanup()


def test_kpi_ranker_uses_resident_generator_without_cloud_fallback(monkeypatch) -> None:
    module = _load_norman_codex_web()
    tmp = _configure_state(module)
    calls: list[dict[str, object]] = []
    try:
        monkeypatch.setattr(module, "WORKING_RECAP_LOCAL_MODEL", "qwen3.8:27b")
        monkeypatch.setattr(
            module, "WORKING_RECAP_LOCAL_ENDPOINTS", ("http://spark.local",)
        )

        def local_generate(endpoint, model, prompt, **kwargs):
            calls.append(
                {"endpoint": endpoint, "model": model, "prompt": prompt, **kwargs}
            )
            return {
                "message": {"content": '["queue","health","local-share","success"]'}
            }

        monkeypatch.setattr(module, "working_recap_local_generate", local_generate)
        module._kpi_dgx_ranking_worker(
            [
                {"id": "queue", "label": "Queue", "value": 1, "tone": "warn"},
                {"id": "health", "label": "Health", "value": "Good", "tone": "ok"},
                {
                    "id": "local-share",
                    "label": "DGX/local",
                    "value": "80%",
                    "tone": "ok",
                },
                {"id": "success", "label": "Success", "value": "100%", "tone": "ok"},
            ],
            "operations",
        )

        ranking = module.load_kpi_dgx_ranking()
        assert calls[0]["endpoint"] == "http://spark.local"
        assert calls[0]["source"] == "tui-kpi-ranker"
        assert ranking["status"] == "ranked"
        assert ranking["model"] == "qwen3.8:27b"
        assert ranking["cloud_fallback"] is False
    finally:
        tmp.cleanup()


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
