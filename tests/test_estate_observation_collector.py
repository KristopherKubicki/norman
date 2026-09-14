"""Verify collector failure isolation and atomic publication."""

import importlib.util
import json
from pathlib import Path
import subprocess

SPEC = importlib.util.spec_from_file_location(
    "estate_collector",
    Path(__file__).parents[1] / "scripts/collect_estate_app_health.py",
)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def test_ssh_failure_is_observation_gap(monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("ssh", 25)

    monkeypatch.setattr(collector.subprocess, "run", fail)
    rows = collector.collect_host("host", {"app": ["app.service"]})
    assert rows[0]["state"] == "observer-unavailable"
    assert rows[0]["level"] == "unknown"


def test_atomic_snapshot_replaces_prior_data(tmp_path, monkeypatch):
    output = tmp_path / "observations.json"
    output.write_text('{"old": true}')
    monkeypatch.setattr(collector, "OUTPUT", output)
    monkeypatch.setattr(collector, "HOST_UNITS", {"host": {"app": []}})
    monkeypatch.setattr(
        collector, "collect_host", lambda *args: [{"application": "app"}]
    )
    monkeypatch.setattr(collector, "collect_aws", lambda: [])
    collector.main()
    assert json.loads(output.read_text())["observations"] == [{"application": "app"}]
    assert not list(tmp_path.glob(".application-observations-*"))


def test_user_service_uses_user_manager(monkeypatch, capsys):
    import sys

    calls = []

    def show(command, **kwargs):
        calls.append(command)
        return "LoadState=loaded\nActiveState=active\nSubState=running\nResult=success\nType=simple\n"

    monkeypatch.setattr(subprocess, "check_output", show)
    monkeypatch.setattr(
        sys,
        "argv",
        ["collector", json.dumps({"earlybird": ["user:earlybird.service"]})],
    )
    exec(collector.REMOTE, {})
    rows = json.loads(capsys.readouterr().out)
    assert calls[0][:4] == ["systemctl", "--user", "show", "earlybird.service"]
    assert rows[0]["state"] == "process-running"
    assert rows[0]["id"] == "user:earlybird.service"


def test_successful_oneshot_is_idle_not_failed(monkeypatch, capsys):
    import sys

    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda *args,
        **kwargs: "LoadState=loaded\nActiveState=inactive\nSubState=dead\nResult=success\nType=oneshot\n",
    )
    monkeypatch.setattr(
        sys, "argv", ["collector", json.dumps({"test": ["sync.service"]})]
    )
    exec(collector.REMOTE, {})
    row = json.loads(capsys.readouterr().out)[0]
    assert row["state"] == "idle"
    assert row["level"] == "ok"
