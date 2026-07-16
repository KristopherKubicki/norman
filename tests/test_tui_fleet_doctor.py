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


def test_doctor_remote_scan_accepts_canonical_norman_env(monkeypatch) -> None:
    module = _load_doctor(monkeypatch)

    source = module.remote_scan_script(("/etc/*/codex-web.env",))

    assert "def env_get(env, config_key" in source
    assert "NORMAN_CODEX_" in source
    assert 'key.startswith(("NORMAN_CODEX", "HOUSEBOT_CODEX"))' in source
    assert 'env_get(env, "NORMAN_CODEX_WEB_PORT")' in source
    assert "/api/restart-readiness" in source
    assert "readiness_url, timeout=4" in source
    assert "status_url, timeout=4" in source
    assert "/api/version" in source


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


def test_default_doctor_skips_private_host_without_console_inventory(
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

    def fake_scan(host):
        assert host.name != "private-host"
        return []

    monkeypatch.setattr(module, "scan_host", fake_scan)

    reports = module.build_reports(
        targets=None,
        min_timeout_seconds=3600,
        ui_version="2026.06.01.7",
    )

    assert "private-host" not in discovered_targets
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
    assert "OnUnitActiveSec=5min" in timer
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
