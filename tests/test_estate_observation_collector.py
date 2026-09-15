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
    monkeypatch.setattr(collector, "WORKFLOW_TARGETS", {})
    monkeypatch.setattr(collector, "collect_endpoints", lambda: [])
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


def test_autoscaling_tracks_group_capacity_not_historic_instance_ids(
    monkeypatch, capsys
):
    import sys

    target = dict(
        kind="asg",
        profile="test",
        account="123",
        region="us-east-2",
        services={"workers": dict(application="crawler", environment="production")},
    )
    response = [
        dict(
            name="workers",
            arn="arn:aws:autoscaling:us-east-2:123:autoScalingGroup:id:autoScalingGroupName/workers",
            desired=2,
            instances=[dict(state="InService", health="Healthy")],
        )
    ]
    monkeypatch.setattr(sys, "argv", ["probe", json.dumps([target])])
    monkeypatch.setattr(
        subprocess, "check_output", lambda *a, **k: json.dumps(response)
    )
    exec(collector.AWS_REMOTE, {})
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 1
    assert rows[0]["state"] == "capacity-shortfall"
    assert rows[0]["environment"] == "production"
    assert rows[0]["metrics"][0]["value"] == 1


def test_failover_required_is_distinct_from_no_available_worker():
    rows = [
        dict(id="gateway-asr-192.168.2.151", host="192.168.2.151", state="unavailable"),
        dict(id="gateway-asr-192.168.2.150", host="192.168.2.150", state="ready"),
    ]
    assert collector.routing_observation(rows)[0]["state"] == "failover-required"
    rows[1]["state"] = "unavailable"
    assert collector.routing_observation(rows)[0]["state"] == "unavailable"


def test_endpoint_probe_rejects_unexpected_content(monkeypatch):
    import io
    import urllib.request

    class Reply(io.BytesIO):
        status = 200

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: Reply(b"<html>login</html>")
    )
    rows = collector.collect_endpoints()
    assert all(r["level"] == "bad" for r in rows)
    assert all(r["metrics"][0]["value"] == 0 for r in rows)
