from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_alerts(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_fleet_alerts", scripts_dir / "tui_fleet_alerts.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_fleet_alerts"] = module
    spec.loader.exec_module(module)
    return module


def _issue(severity: str, detail: str = "busy/running - 5m elapsed") -> dict:
    return {
        "severity": severity,
        "host": "work-special",
        "instance": "panelbot",
        "check": "runtime",
        "detail": detail,
    }


def test_alert_policy_posts_failures_immediately_and_debounces_warnings(
    monkeypatch,
) -> None:
    module = _load_alerts(monkeypatch)
    fail = _issue("fail", "queue has 1 item(s) but no prompt is running")
    busy_warn = _issue("warn")
    abandoned_warn = _issue(
        "warn",
        "last prompt failed: Web prompt was abandoned after restart; "
        "no running model process was found.",
    )
    alertable_warn = _issue("warn", "last_error present while state is not failed")
    health = {
        "checked_at": "2026-05-28T05:47:49Z",
        "status": "fail",
        "summary": {"active": 30, "expected": 30, "fail": 1, "warn": 3},
        "issues": [fail, busy_warn, abandoned_warn, alertable_warn],
    }

    first = module.evaluate_alerts(health, {}, warn_threshold=2)

    assert [item["severity"] for item in first["new_alerts"]] == ["fail"]
    assert len(first["suppressed_warnings"]) == 1
    assert len(first["ignored_warnings"]) == 2
    assert list(first["next_state"]["warning_counts"].values()) == [1]

    second = module.evaluate_alerts(
        {
            **health,
            "checked_at": "2026-05-28T06:17:49Z",
            "status": "warn",
            "issues": [alertable_warn],
        },
        first["next_state"],
        warn_threshold=2,
    )

    assert [item["severity"] for item in second["new_alerts"]] == ["warn"]
    assert second["suppressed_warnings"] == []

    third = module.evaluate_alerts(
        {
            **health,
            "checked_at": "2026-05-28T06:47:49Z",
            "status": "warn",
            "issues": [alertable_warn],
        },
        second["next_state"],
        warn_threshold=2,
    )

    assert third["new_alerts"] == []
    assert len(third["alert_issues"]) == 1


def test_alert_policy_is_idempotent_for_same_doctor_timestamp(monkeypatch) -> None:
    module = _load_alerts(monkeypatch)
    warn = _issue("warn", "last_error present while state is not failed")
    state = {
        "last_checked_at": "2026-05-28T05:47:49Z",
        "warning_counts": {module.issue_signature(warn): 1},
        "active_alert_signatures": [],
    }

    decision = module.evaluate_alerts(
        {
            "checked_at": "2026-05-28T05:47:49Z",
            "status": "warn",
            "summary": {"active": 30, "warn": 1},
            "issues": [warn],
        },
        state,
        warn_threshold=2,
    )

    assert decision["already_seen"] is True
    assert decision["new_alerts"] == []
    assert decision["next_state"] is state


def test_alert_policy_resets_resolved_signatures(monkeypatch) -> None:
    module = _load_alerts(monkeypatch)
    warn = _issue("warn")
    signature = module.issue_signature(warn)

    decision = module.evaluate_alerts(
        {"status": "ok", "summary": {"active": 30}, "issues": []},
        {
            "active_alert_signatures": [signature],
            "warning_counts": {signature: 2},
        },
        warn_threshold=2,
    )

    assert decision["new_alerts"] == []
    assert decision["next_state"]["warning_counts"] == {}
    assert decision["next_state"]["active_alert_signatures"] == []
    assert decision["resolved_signatures"] == [signature]


def test_alert_policy_compacts_noisy_remote_scan_details(monkeypatch) -> None:
    module = _load_alerts(monkeypatch)
    issue = _issue(
        "fail",
        "CalledProcessError: Command '['ssh', 'root@192.168.2.147', "
        "'bash -lc \"python3 - <<PY\"'] returned non-zero exit status 255.",
    )

    assert (
        module.normalized_issue_detail(issue)
        == "ssh scan failed; remote probe did not complete"
    )
    assert module.issue_signature(issue).endswith(
        "|ssh scan failed; remote probe did not complete"
    )

    body = module.render_alert_body(
        {
            "checked_at": "2026-06-07T18:38:48Z",
            "summary": {"active": 18, "expected": 18, "fail": 1, "warn": 0},
        },
        {"new_alerts": [issue], "suppressed_warnings": [], "ignored_warnings": []},
    )

    assert "Action needed:" in body
    assert "work-special/panelbot" in body
    assert "ssh scan failed; remote probe did not complete" in body
    assert "python3 - <<PY" not in body


def test_alert_post_creates_thread_and_posts_message(monkeypatch) -> None:
    module = _load_alerts(monkeypatch)
    calls = []

    def fake_request(method, url, *, token, payload=None, timeout=15.0):
        calls.append((method, url, token, payload))
        if method == "GET":
            return 404, {"ok": False, "error": "not_found"}
        return 201, {"ok": True}

    monkeypatch.setattr(module, "_request", fake_request)
    decision = {
        "new_alerts": [_issue("fail", "queue has 1 item(s) but no prompt is running")],
        "suppressed_warnings": [],
    }
    health = {
        "checked_at": "2026-05-28T05:47:49Z",
        "status": "fail",
        "summary": {"active": 30, "expected": 30, "fail": 1, "warn": 0},
    }

    module.post_alert(
        base_url="http://bbs.local",
        token="secret",
        actor="norman",
        thread_id="th_tui_fleet_health",
        health=health,
        decision=decision,
    )

    assert calls[0][0] == "GET"
    assert calls[1][0:2] == ("POST", "http://bbs.local/api/v1/threads")
    assert calls[1][3]["watchers"] == ["panelbot", "netops"]
    assert calls[2][0] == "POST"
    assert calls[2][3]["kind"] == "alert"
    assert "TUI fleet health alert" in calls[2][3]["body"]
    assert "Action needed:" in calls[2][3]["body"]
    assert calls[2][3]["metadata"]["has_failure"] is True


def test_tui_fleet_alerts_systemd_path_triggers_on_doctor_json() -> None:
    root = Path(__file__).resolve().parents[1]
    service = (
        root / "scripts" / "systemd" / "norman-tui-fleet-alerts.service"
    ).read_text(encoding="utf-8")
    path = (root / "scripts" / "systemd" / "norman-tui-fleet-alerts.path").read_text(
        encoding="utf-8"
    )

    assert "scripts/tui_fleet_alerts.py" in service
    assert "User=root" in service
    assert (
        "PathChanged=/home/kristopher/.local/state/norman/tui-fleet-doctor.json" in path
    )
    assert "Unit=norman-tui-fleet-alerts.service" in path
