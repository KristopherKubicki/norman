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
