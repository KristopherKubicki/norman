from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_doctor(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_fleet_doctor", scripts_dir / "tui_fleet_doctor.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_fleet_doctor"] = module
    spec.loader.exec_module(module)
    return module


def _row(name: str, **overrides):
    row = {
        "name": name,
        "timeout": "3600",
        "ui_version": "2026.06.01.7",
        "stale_refs": [],
        "configured_model": "gpt-5.6-terra",
        "model_floor": "gpt-5.6-terra",
        "runtime_model": "gpt-5.6-terra",
        "local_llm_execution_enabled": "1",
        "status": {
            "state": "ok",
            "pending": False,
            "queue_depth": 0,
            "active_child_pid": 0,
            "last_error": "",
            "auth": {"required": False},
        },
        "status_error": "",
    }
    row.update(overrides)
    return row


def _issues(report):
    return {(issue.severity, issue.instance, issue.check) for issue in report.issues}


def _issue_details(report):
    return {
        (issue.severity, issue.instance, issue.check): issue.detail
        for issue in report.issues
    }


def test_doctor_accepts_clean_active_inventory(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="toy-box",
        expected_names={"studio"},
        active_rows=[_row("studio")],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    assert report.ok is True
    assert report.issues == []


def test_workflow_controls_are_private_staged_and_do_not_degrade_fleet_health(
    monkeypatch,
) -> None:
    module = _load_doctor(monkeypatch)

    payload = module.build_payload([], "2026.07.26.1")
    workflow = payload["workflow_health"]

    assert payload["status"] == "ok"
    assert payload["summary"]["fail"] == 0
    assert workflow["visibility"] == "private"
    assert workflow["summary"] == {
        "controls": 3,
        "staged": 3,
        "not_deployed": 3,
        "live_status_sources": 0,
    }
    assert [control["id"] for control in workflow["controls"]] == [
        "openbrand_webgoat_staging_boundary_control",
        "openbrand_product_placement_recovery_control",
        "openbrand_category_launch_coverage_flash",
    ]
    for control in workflow["controls"]:
        assert control["deployment_state"] == "not_deployed"
        assert control["visibility"] == "private"
        assert control["live_status_source"] is False
        assert control["public_status_eligible"] is False

    markdown = module.render_markdown([], "2026.07.26.1")
    assert (
        "Staged controls do not affect fleet status or public availability." in markdown
    )


def test_doctor_tracks_deferred_web_restart_until_its_safety_deadline(
    monkeypatch,
) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="toy-box",
        expected_names={"housebot"},
        active_rows=[
            _row(
                "housebot",
                ui_version="2026.07.22.1",
                status={
                    "state": "running",
                    "pending": True,
                    "queue_depth": 0,
                    "active_child_pid": 321,
                    "web_restart_required": True,
                    "web_restart_reason": "console web script changed after start",
                    "web_restart_deferred": True,
                    "web_restart_deferred_at": 1_700_000_000,
                    "web_restart_deferred_deadline_at": 1_700_000_900,
                    "web_restart_deferred_expired_at": 0,
                    "busy_reasons": ["pending_prompt", "model_process_alive"],
                    "auth": {"required": False},
                },
            )
        ],
        archived_names=set(),
        min_timeout_seconds=3600,
        ui_version="2026.07.22.2",
        now=1_700_000_120,
    )

    details = _issue_details(report)
    assert report.ok is True
    assert ("warn", "housebot", "web-restart-deferred") in details
    assert "waiting 120s/900s" in details[("warn", "housebot", "web-restart-deferred")]
    assert ("warn", "housebot", "ui-version") in details

    payload = module.build_payload([report], "2026.07.22.2")
    assert payload["deployment_closure"] == {
        "ready": False,
        "version_mismatch": 1,
        "restart_staged": 1,
        "restart_deferred": 1,
        "restart_expired": 0,
    }


def test_doctor_escalates_expired_deferred_web_restart(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="toy-box",
        expected_names={"housebot"},
        active_rows=[
            _row(
                "housebot",
                ui_version="2026.07.22.1",
                status={
                    "state": "running",
                    "pending": True,
                    "queue_depth": 0,
                    "active_child_pid": 321,
                    "web_restart_required": True,
                    "web_restart_deferred_at": 1_700_000_000,
                    "web_restart_deferred_expired_at": 1_700_000_900,
                    "auth": {"required": False},
                },
            )
        ],
        archived_names=set(),
        min_timeout_seconds=3600,
        ui_version="2026.07.22.2",
        now=1_700_000_960,
    )

    details = _issue_details(report)
    assert report.ok is False
    assert ("fail", "housebot", "web-restart-expired") in details
    assert "expired 60s ago" in details[("fail", "housebot", "web-restart-expired")]
    assert ("fail", "housebot", "ui-version") in details


def test_doctor_remote_scan_accepts_canonical_norman_env(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    source = module.remote_scan_script(("/etc/*/codex-web.env",))

    assert "def env_get(env, config_key" in source
    assert "NORMAN_CODEX_" in source
    assert 'key.startswith(("NORMAN_CODEX", "HOUSEBOT_CODEX"))' in source
    assert 'env_get(env, "NORMAN_CODEX_WEB_PORT")' in source
    assert "/api/restart-readiness" in source
    assert "status_url, timeout=4" in source
    assert "readiness_url, timeout=4" in source
    assert "/api/version" in source
    assert "def runtime_model(env):" in source
    assert '"local_llm_execution_enabled"' in source


def test_doctor_fails_legacy_model_or_disabled_local_first(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="toy-box",
        expected_names={"artmonster"},
        active_rows=[
            _row(
                "artmonster",
                configured_model="gpt-5.4",
                model_floor="gpt-5.6-terra",
                runtime_model="gpt-5.4",
                local_llm_execution_enabled="0",
            )
        ],
        archived_names=set(),
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    details = _issue_details(report)
    assert ("fail", "artmonster", "model-policy") in details
    assert ("fail", "artmonster", "local-first") in details


def test_doctor_keeps_last_prompt_failure_cause_in_warning(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="work-special",
        expected_names={"infra"},
        active_rows=[
            _row(
                "infra",
                status={
                    "state": "error",
                    "pending": False,
                    "queue_depth": 0,
                    "active_child_pid": 0,
                    "last_error": "Bedrock provider failure before usable tokens.",
                    "auth": {"required": False},
                },
            )
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    details = _issue_details(report)

    assert report.ok is True
    assert details[("warn", "infra", "runtime")] == (
        "last prompt failed: Bedrock provider failure before usable tokens."
    )


def test_doctor_suppresses_stale_preflight_failure_after_live_probe(
    monkeypatch,
) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="work-special",
        expected_names={"publisher"},
        active_rows=[
            _row(
                "publisher",
                preflight_probe="ready",
                status={
                    "state": "error",
                    "pending": False,
                    "queue_depth": 0,
                    "active_child_pid": 0,
                    "last_error": (
                        "TUI release preflight blocked this route before Codex "
                        "started. Read readiness.md for recovery."
                    ),
                    "auth": {"required": False},
                },
            )
        ],
        archived_names=set(),
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    assert report.ok is True
    assert ("warn", "publisher", "runtime") not in _issues(report)


def test_doctor_compacts_failed_ssh_scan_detail(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)
    host = module.sync.HOSTS["work-special"]
    monkeypatch.setattr(
        module,
        "_host_reachability_summary",
        lambda _host: "192.168.2.147:22 connected; no SSH banner within 2s",
    )

    exc = module.subprocess.CalledProcessError(
        255,
        ["ssh", "root@192.168.2.147", "python3 - <<PY"],
        stderr="Connection timed out during banner exchange\n",
    )

    detail = module.summarize_scan_failure(host, exc)

    assert "SSH banner timeout" in detail
    assert "connected; no SSH banner" in detail
    assert "scripts/tui_host_recovery.py --target work-special" in detail
    assert "python3 - <<PY" not in detail
    assert len(detail) < 320


def test_default_doctor_includes_private_host_inventory(
    monkeypatch,
) -> None:
    module = _load_doctor(monkeypatch)
    discovered_targets = []

    def fake_discover(targets):
        discovered_targets.extend(targets or [])
        return ({target: [] for target in targets or []}, [])

    monkeypatch.setattr(
        module.sync,
        "discover_all_instances",
        fake_discover,
    )

    def fake_scan(_host):
        return []

    monkeypatch.setattr(module, "scan_host", fake_scan)

    reports = module.build_reports(
        targets=None,
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    assert "private-host" in discovered_targets
    private_report = next(report for report in reports if report.host == "private-host")
    assert private_report.active_count == 0
    assert private_report.expected_count == 0
    assert private_report.issues == []


def test_doctor_rejects_stale_wrappers_and_low_timeout(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="toy-box",
        expected_names={"castle"},
        active_rows=[
            _row(
                "castle",
                timeout="900",
                stale_refs=[
                    "/etc/systemd/system/castle-codex.service:housebot_codex:ExecStart=/opt/housebot/scripts/housebot_codex_supervisor.sh"
                ],
            )
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    assert report.ok is False
    assert ("fail", "castle", "wrapper-path") in _issues(report)
    assert ("fail", "castle", "timeout") in _issues(report)


def test_doctor_fails_critical_host_pressure_with_recovery_hint(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="work-special",
        expected_names={"mls"},
        active_rows=[
            _row(
                "mls",
                host_pressure={
                    "cpu_some": 25.99,
                    "io_some": 97.93,
                    "mem_some": 63.35,
                },
            )
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    details = _issue_details(report)
    assert ("fail", "<host>", "host-pressure") in details
    assert "critical host pressure" in details[("fail", "<host>", "host-pressure")]
    assert (
        "io_some=97.93 >= critical 80" in details[("fail", "<host>", "host-pressure")]
    )
    assert (
        "scripts/tui_host_recovery.py --target work-special"
        in details[("fail", "<host>", "host-pressure")]
    )


def test_doctor_warns_elevated_host_pressure(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="toy-box",
        expected_names={"studio"},
        active_rows=[_row("studio", host_pressure={"io_some": 55.5})],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    details = _issue_details(report)
    assert ("warn", "<host>", "host-pressure") in details
    assert "elevated host pressure" in details[("warn", "<host>", "host-pressure")]


def test_doctor_allows_owner_named_wrappers(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="toy-box",
        expected_names={"housebot"},
        active_rows=[
            _row(
                "housebot",
                stale_refs=[
                    "/etc/systemd/system/housebot-codex.service:housebot_codex:ExecStart=/opt/housebot/scripts/housebot_codex_supervisor.sh"
                ],
            )
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    assert report.ok is True
    assert report.issues == []


def test_doctor_flags_archived_active_and_missing_expected(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="work-special",
        expected_names={"mls"},
        active_rows=[_row("publisher")],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    assert report.ok is False
    assert ("fail", "publisher", "inventory") in _issues(report)
    assert ("fail", "mls", "service") in _issues(report)


def test_doctor_distinguishes_busy_from_failed_runtime(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="work-special",
        expected_names={"panelbot", "mls"},
        active_rows=[
            _row(
                "panelbot",
                status={
                    "state": "running",
                    "pending": True,
                    "queue_depth": 0,
                    "active_child_pid": 123,
                    "last_error": "",
                    "auth": {"required": False},
                },
            ),
            _row(
                "mls",
                status={
                    "state": "error",
                    "pending": False,
                    "queue_depth": 0,
                    "active_child_pid": 0,
                    "last_error": "stale auth",
                    "auth": {"required": True, "summary": "needs sign-in"},
                },
            ),
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    assert report.ok is False
    assert ("warn", "panelbot", "runtime") in _issues(report)
    assert ("fail", "mls", "auth") in _issues(report)
    assert ("fail", "mls", "runtime") in _issues(report)


def test_doctor_treats_completed_prompt_timeout_as_attention(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="work-special",
        expected_names={"panelbot"},
        active_rows=[
            _row(
                "panelbot",
                status={
                    "state": "error",
                    "pending": False,
                    "queue_depth": 0,
                    "active_child_pid": 0,
                    "last_error": "Web prompt timed out after 3600 seconds and was terminated.",
                    "auth": {"required": False},
                },
            )
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    assert report.ok is True
    assert ("warn", "panelbot", "runtime") in _issues(report)


def test_doctor_still_fails_error_state_with_active_prompt(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="work-special",
        expected_names={"panelbot"},
        active_rows=[
            _row(
                "panelbot",
                status={
                    "state": "error",
                    "pending": True,
                    "queue_depth": 0,
                    "active_child_pid": 123,
                    "last_error": "worker failed while prompt was active",
                    "auth": {"required": False},
                },
            )
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    assert report.ok is False
    assert ("fail", "panelbot", "runtime") in _issues(report)


def test_doctor_reports_busy_runtime_against_selected_budget(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)
    monkeypatch.setattr(module.time, "time", lambda: 10_000)

    report = module.analyze_host(
        host_name="networking-host",
        expected_names={"cloudagent"},
        active_rows=[
            _row(
                "cloudagent",
                status={
                    "state": "running",
                    "pending": True,
                    "queue_depth": 0,
                    "active_child_pid": 123,
                    "active_child_started_at": 8_200,
                    "last_error": "",
                    "running_job_budget": "deep",
                    "running_timeout_seconds": 7200,
                    "auth": {"required": False},
                },
            )
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    details = _issue_details(report)

    assert report.ok is True
    assert ("warn", "cloudagent", "runtime") in details
    assert "30m elapsed" in details[("warn", "cloudagent", "runtime")]
    assert "2h budget" in details[("warn", "cloudagent", "runtime")]
    assert "budget=deep" in details[("warn", "cloudagent", "runtime")]


def test_doctor_fails_running_prompt_that_exceeds_selected_budget(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)
    monkeypatch.setattr(module.time, "time", lambda: 10_000)

    report = module.analyze_host(
        host_name="work-special",
        expected_names={"panelbot"},
        active_rows=[
            _row(
                "panelbot",
                status={
                    "state": "running",
                    "pending": True,
                    "queue_depth": 0,
                    "active_child_pid": 123,
                    "active_child_started_at": 5_000,
                    "last_error": "",
                    "running_job_budget": "normal",
                    "running_timeout_seconds": 3600,
                    "auth": {"required": False},
                },
            )
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    assert report.ok is False
    assert ("fail", "panelbot", "runtime") in _issues(report)


def test_doctor_warns_stale_active_child_ref_without_degrading(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)
    monkeypatch.setattr(module.time, "time", lambda: 10_000)

    report = module.analyze_host(
        host_name="hal",
        expected_names={"autocamera"},
        active_rows=[
            _row(
                "autocamera",
                status={
                    "state": "ok",
                    "pending": False,
                    "queue_depth": 0,
                    "active_child_pid": 123,
                    "active_child_started_at": 5_000,
                    "web_worker_alive": False,
                    "model_process_alive": False,
                    "last_error": "",
                    "running_job_budget": "normal",
                    "running_timeout_seconds": 3600,
                    "auth": {"required": False},
                },
            )
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    details = _issue_details(report)

    assert report.ok is True
    assert ("warn", "autocamera", "runtime") in details
    assert "stale active_child_pid=123" in details[("warn", "autocamera", "runtime")]
    assert ("fail", "autocamera", "runtime") not in details


def test_doctor_warns_recovered_queue_without_running_prompt(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="work-special",
        expected_names={"panelbot"},
        active_rows=[
            _row(
                "panelbot",
                status={
                    "state": "ok",
                    "pending": False,
                    "queue_depth": 2,
                    "active_child_pid": 0,
                    "stale_queue": True,
                    "last_error": "",
                    "auth": {"required": False},
                },
            )
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    details = _issue_details(report)

    assert report.ok is True
    assert ("warn", "panelbot", "queue") in details
    assert "recovered queue requires review" in details[("warn", "panelbot", "queue")]
    assert ("warn", "panelbot", "runtime") not in details


def test_doctor_warns_when_web_restart_is_staged(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="work-special",
        expected_names={"panelbot"},
        active_rows=[
            _row(
                "panelbot",
                ui_version="2026.06.01.6",
                status={
                    "state": "ok",
                    "pending": False,
                    "queue_depth": 0,
                    "active_child_pid": 0,
                    "web_restart_required": True,
                    "web_restart_reason": "Console web script changed after this process started.",
                    "last_error": "",
                    "auth": {"required": False},
                },
            )
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    details = _issue_details(report)

    assert report.ok is True
    assert ("warn", "panelbot", "ui-version") in details
    assert "2026.06.01.6 != 2026.06.01.7" in details[("warn", "panelbot", "ui-version")]
    assert ("warn", "panelbot", "web-restart") in details
    assert "Console web script changed" in details[("warn", "panelbot", "web-restart")]


def test_doctor_fails_unexplained_ui_version_mismatch(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="work-special",
        expected_names={"panelbot"},
        active_rows=[
            _row(
                "panelbot",
                ui_version="2026.06.01.6",
                status={
                    "state": "ok",
                    "pending": False,
                    "queue_depth": 0,
                    "active_child_pid": 0,
                    "web_restart_required": False,
                    "last_error": "",
                    "auth": {"required": False},
                },
            )
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    details = _issue_details(report)

    assert report.ok is False
    assert ("fail", "panelbot", "ui-version") in details


def test_doctor_fails_stuck_queue_without_running_prompt(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="work-special",
        expected_names={"panelbot"},
        active_rows=[
            _row(
                "panelbot",
                status={
                    "state": "ok",
                    "pending": False,
                    "queue_depth": 2,
                    "active_child_pid": 0,
                    "stale_queue": False,
                    "last_error": "",
                    "auth": {"required": False},
                },
            )
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    details = _issue_details(report)

    assert report.ok is False
    assert ("fail", "panelbot", "queue") in details
    assert "no prompt is running" in details[("fail", "panelbot", "queue")]


def test_doctor_fails_pending_prompt_without_worker(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    report = module.analyze_host(
        host_name="work-special",
        expected_names={"panelbot"},
        active_rows=[
            _row(
                "panelbot",
                status={
                    "state": "running",
                    "pending": True,
                    "queue_depth": 0,
                    "active_child_pid": 0,
                    "web_worker_alive": False,
                    "model_process_alive": False,
                    "last_error": "",
                    "auth": {"required": False},
                },
            )
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    details = _issue_details(report)

    assert report.ok is False
    assert ("fail", "panelbot", "runtime") in details
    assert "no live web worker" in details[("fail", "panelbot", "runtime")]


def test_doctor_allows_recent_tmux_owned_pending_prompt_without_liveness(
    monkeypatch,
) -> None:
    module = _load_doctor(monkeypatch)
    monkeypatch.setattr(module.time, "time", lambda: 10_000)

    report = module.analyze_host(
        host_name="norman",
        expected_names={"norman"},
        active_rows=[
            _row(
                "norman",
                status={
                    "state": "running",
                    "pending": True,
                    "queue_depth": 0,
                    "active_child_pid": 0,
                    "last_started_at": 9_000,
                    "running_job_budget": "normal",
                    "running_timeout_seconds": 3_600,
                    "last_error": "",
                    "auth": {"required": False},
                },
            )
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    assert report.ok is True
    assert ("fail", "norman", "runtime") not in _issues(report)
    assert ("warn", "norman", "runtime") in _issues(report)


def test_doctor_fails_overdue_tmux_owned_pending_prompt_without_liveness(
    monkeypatch,
) -> None:
    module = _load_doctor(monkeypatch)
    monkeypatch.setattr(module.time, "time", lambda: 10_000)

    report = module.analyze_host(
        host_name="norman",
        expected_names={"norman"},
        active_rows=[
            _row(
                "norman",
                status={
                    "state": "running",
                    "pending": True,
                    "queue_depth": 0,
                    "active_child_pid": 0,
                    "last_started_at": 5_000,
                    "running_job_budget": "normal",
                    "running_timeout_seconds": 3_600,
                    "last_error": "",
                    "auth": {"required": False},
                },
            )
        ],
        archived_names={"publisher"},
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    details = _issue_details(report)

    assert report.ok is False
    assert ("fail", "norman", "runtime") in details
    assert any(
        issue.severity == "fail"
        and issue.instance == "norman"
        and issue.check == "runtime"
        and "no live web worker" in issue.detail
        for issue in report.issues
    )


def test_tui_fleet_doctor_systemd_timer_runs_script() -> None:
    root = Path(__file__).resolve().parents[1]
    service = (
        root / "scripts" / "systemd" / "norman-tui-fleet-doctor.service"
    ).read_text(encoding="utf-8")
    timer = (root / "scripts" / "systemd" / "norman-tui-fleet-doctor.timer").read_text(
        encoding="utf-8"
    )

    assert "scripts/tui_fleet_doctor.py" in service
    assert "User=kristopher" in service
    assert (
        "ExecStartPre=/usr/bin/mkdir -p /home/kristopher/.local/state/norman" in service
    )
    assert (
        "--output /home/kristopher/.local/state/norman/tui-fleet-doctor.md" in service
    )
    assert (
        "--json-output /home/kristopher/.local/state/norman/tui-fleet-doctor.json"
        in service
    )
    assert (
        "--route-proof-json /home/kristopher/.local/state/norman/"
        "tui-status-route-proof.json"
    ) in service
    assert "--route-proof-max-age-seconds 2700" in service
    assert (
        "--cold-recovery-proof-json /home/kristopher/.local/state/norman/"
        "tui-cold-recovery-drill.json"
    ) in service
    assert "--cold-recovery-proof-max-age-seconds 32400" in service
    assert "NORMAN_SYNC_EXECUTION_HOST=norman" not in service
    assert "OnUnitActiveSec=5min" in timer
    assert "Persistent=true" in timer
    route_proof_timer = (
        root / "scripts" / "systemd" / "norman-tui-route-proof.timer"
    ).read_text(encoding="utf-8")
    assert "OnActiveSec=5min" in route_proof_timer
    assert "OnUnitActiveSec=30min" in route_proof_timer


def test_route_proof_report_requires_fresh_successful_terra_proof(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_doctor(monkeypatch)
    proof = tmp_path / "route-proof.json"
    proof.write_text(
        json.dumps(
            {
                "live": True,
                "generated_at": 1_700_000_000,
                "summary": {
                    "targets": 4,
                    "passed": 4,
                    "failed": 0,
                    "named_codexspark_access_check_contract_ok": True,
                    "route_scorecard": {"observed_turns": 4},
                },
            }
        ),
        encoding="utf-8",
    )

    report = module.route_proof_report(proof, max_age_seconds=2700, now=1_700_000_100)

    assert report.ok is True
    assert report.issues == []


def test_route_proof_report_flags_missing_stale_and_failed_evidence(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_doctor(monkeypatch)
    missing = module.route_proof_report(
        tmp_path / "missing.json", max_age_seconds=2700, now=1_700_000_100
    )
    assert ("fail", "<fleet-canary>", "route-proof") in _issues(missing)

    proof = tmp_path / "route-proof.json"
    proof.write_text(
        json.dumps(
            {
                "live": True,
                "generated_at": 1_699_990_000,
                "summary": {
                    "targets": 4,
                    "passed": 3,
                    "failed": 1,
                    "named_codexspark_access_check_contract_ok": False,
                    "route_scorecard": {"observed_turns": 3},
                },
            }
        ),
        encoding="utf-8",
    )
    failed = module.route_proof_report(proof, max_age_seconds=2700, now=1_700_000_100)
    details = [issue.detail for issue in failed.issues]

    assert "scheduled live route proof is stale" in details
    assert any("live route proof failed" in detail for detail in details)
    assert any("codexspark" in detail for detail in details)


def test_route_proof_report_requires_completed_turn_scorecard(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_doctor(monkeypatch)
    proof = tmp_path / "route-proof.json"
    proof.write_text(
        json.dumps(
            {
                "live": True,
                "generated_at": 1_700_000_000,
                "summary": {
                    "targets": 1,
                    "passed": 1,
                    "failed": 0,
                    "named_codexspark_access_check_contract_ok": True,
                },
            }
        ),
        encoding="utf-8",
    )

    report = module.route_proof_report(proof, max_age_seconds=2700, now=1_700_000_100)

    assert report.ok is False
    assert any(
        "route scorecard is missing completed-turn evidence" in issue.detail
        for issue in report.issues
    )


def test_cold_recovery_report_requires_fresh_isolated_no_inference_proof(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_doctor(monkeypatch)
    proof = tmp_path / "cold-recovery-drill.json"
    proof.write_text(
        json.dumps(
            {
                "live": False,
                "mode": "cold-recovery-drill",
                "generated_at": 1_700_000_000,
                "summary": {
                    "targets": 4,
                    "passed": 4,
                    "failed": 0,
                    "isolated_no_inference": True,
                    "stale_timeout_recovery_verified": True,
                },
            }
        ),
        encoding="utf-8",
    )

    report = module.cold_recovery_proof_report(
        proof, max_age_seconds=32400, now=1_700_000_100
    )

    assert report.ok is True
    assert report.issues == []


def test_cold_recovery_report_flags_missing_mode_invariant_and_recovery_failures(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_doctor(monkeypatch)
    missing = module.cold_recovery_proof_report(
        tmp_path / "missing.json", max_age_seconds=32400, now=1_700_000_100
    )
    assert ("fail", "<fleet-canary>", "cold-recovery-proof") in _issues(missing)

    proof = tmp_path / "cold-recovery-drill.json"
    proof.write_text(
        json.dumps(
            {
                "live": True,
                "mode": "status-route-proof",
                "generated_at": 1_699_960_000,
                "summary": {
                    "targets": 4,
                    "passed": 3,
                    "failed": 1,
                    "isolated_no_inference": False,
                    "stale_timeout_recovery_verified": False,
                },
            }
        ),
        encoding="utf-8",
    )

    report = module.cold_recovery_proof_report(
        proof, max_age_seconds=32400, now=1_700_000_100
    )
    details = [issue.detail for issue in report.issues]

    assert "scheduled no-inference cold-recovery drill is stale" in details
    assert any("not an isolated no-inference drill" in detail for detail in details)
    assert any("cold-recovery drill failed" in detail for detail in details)
    assert any("no-inference invariant" in detail for detail in details)
    assert any("stale planner timeout recovery" in detail for detail in details)


def test_route_proof_timer_runs_canary_set() -> None:
    root = Path(__file__).resolve().parents[1]
    service = (
        root / "scripts" / "systemd" / "norman-tui-route-proof.service"
    ).read_text(encoding="utf-8")
    timer = (root / "scripts" / "systemd" / "norman-tui-route-proof.timer").read_text(
        encoding="utf-8"
    )

    assert "scripts/tui_status_route_proof.py --live" in service
    assert "--targets uplink norman publisher platinum-standard" in service
    assert "tui-status-route-proof.json" in service
    assert "TimeoutStartSec=10min" in service
    assert "NORMAN_SYNC_EXECUTION_HOST=norman" not in service
    assert "OnUnitActiveSec=30min" in timer
    assert "Persistent=true" in timer


def test_cold_recovery_timer_runs_no_inference_canary_set() -> None:
    root = Path(__file__).resolve().parents[1]
    service = (
        root / "scripts" / "systemd" / "norman-tui-cold-recovery-drill.service"
    ).read_text(encoding="utf-8")
    timer = (
        root / "scripts" / "systemd" / "norman-tui-cold-recovery-drill.timer"
    ).read_text(encoding="utf-8")

    assert "scripts/tui_status_route_proof.py --cold-recovery-drill" in service
    assert "--targets uplink norman publisher platinum-standard" in service
    assert "tui-cold-recovery-drill.json" in service
    assert "TimeoutStartSec=5min" in service
    assert "NORMAN_SYNC_EXECUTION_HOST=norman" not in service
    assert "OnUnitActiveSec=6h" in timer
    assert "Persistent=true" in timer


def test_tui_fleet_doctor_writes_structured_health_state(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_doctor(monkeypatch)
    reports = [
        module.HostReport(
            host="work-special",
            active_count=1,
            expected_count=1,
            issues=[
                module.DoctorIssue(
                    "warn",
                    "work-special",
                    "panelbot",
                    "runtime",
                    "busy/running · 3m elapsed",
                )
            ],
        )
    ]
    monkeypatch.setattr(module, "expected_ui_version", lambda: "2026.06.01.7")
    monkeypatch.setattr(module, "build_reports", lambda **_: reports)
    output = tmp_path / "health.json"
    markdown = tmp_path / "health.md"

    assert (
        module.main(
            [
                "--json",
                "--output",
                str(output),
                "--markdown-output",
                str(markdown),
            ]
        )
        == 0
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["available"] is True
    assert payload["status"] == "warn"
    assert payload["expected_ui_version"] == "2026.06.01.7"
    assert payload["summary"] == {
        "active": 1,
        "expected": 1,
        "fail": 0,
        "hosts": 1,
        "ok": True,
        "warn": 1,
    }
    assert payload["issues"][0]["instance"] == "panelbot"
    assert "Summary: active=1, fail=0, warn=1" in markdown.read_text(encoding="utf-8")
