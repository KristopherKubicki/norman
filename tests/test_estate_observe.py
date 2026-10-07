"""Collectors keep unavailable evidence explicit and publish snapshots atomically."""

import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def observer(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "estate_observe_test", scripts / "estate_observe.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "failure",
    [
        OSError("private diagnostic"),
        subprocess.TimeoutExpired("ssh", 25),
        ValueError("invalid output"),
    ],
)
def test_failed_host_observation_is_unknown_not_healthy(observer, monkeypatch, failure):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(observer.subprocess, "run", fail)
    rows = observer.collect_host("hal", {"autocamera": ["autocamera-webcam.service"]})
    assert rows[0]["state"] == "observer-unavailable"
    assert rows[0]["level"] == "unknown"
    assert "private" not in json.dumps(rows)
    assert "metrics" not in rows[0]


def test_aws_observer_outage_preserves_application_identity(
    observer, monkeypatch, tmp_path
):
    target = tmp_path / "targets.json"
    target.write_text(json.dumps([{"services": {"audio": {"application": "deepad"}}}]))
    monkeypatch.setattr(observer, "TARGETS", target)
    monkeypatch.setattr(
        observer.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="not json")
    )
    row = observer.collect_aws()[0]
    assert (row["application"], row["id"], row["level"]) == (
        "deepad",
        "audio",
        "unknown",
    )


def test_missing_workflow_dependency_is_reported(observer, monkeypatch, tmp_path):
    monkeypatch.setattr(observer, "__file__", str(tmp_path / "collector.py"))
    rows = observer.collect_workflow(("work-special", "earlybird"))
    assert rows[0]["state"] == "observer-unavailable"


@pytest.mark.parametrize(
    "primary,secondary,state",
    [
        ("ready", "ready", "primary-ready"),
        ("unavailable", "ready", "failover-required"),
        ("unavailable", "unavailable", "unavailable"),
    ],
)
def test_routing_requires_both_known_worker_observations(
    observer, primary, secondary, state
):
    rows = [
        {"host": host, "id": "gateway-asr-" + host, "state": value}
        for host, value in [("192.168.2.151", primary), ("192.168.2.150", secondary)]
    ]
    assert observer.routing_observation(rows)[0]["state"] == state
    assert observer.routing_observation(rows[:1]) == []
    rows[1]["host"] = "unexpected-worker"
    assert observer.routing_observation(rows) == []


def test_failed_publication_preserves_previous_snapshot(
    observer, monkeypatch, tmp_path
):
    output = tmp_path / "observations.json"
    output.write_text('{"previous":true}\n')
    monkeypatch.setattr(observer, "OUTPUT", output)
    monkeypatch.setattr(observer, "HOST_UNITS", {})
    monkeypatch.setattr(observer, "WORKFLOW_TARGETS", {})
    monkeypatch.setattr(observer, "collect_aws", lambda: [])
    monkeypatch.setattr(observer, "collect_endpoints", lambda: [])

    def fail(*args):
        raise OSError("replace interrupted")

    monkeypatch.setattr(observer.os, "replace", fail)
    with pytest.raises(OSError, match="replace interrupted"):
        observer.main()
    assert json.loads(output.read_text()) == {"previous": True}
    assert not list(tmp_path.glob(".application-observations-*"))


def test_successful_publication_contains_only_collected_rows(
    observer, monkeypatch, tmp_path
):
    output = tmp_path / "observations.json"
    monkeypatch.setattr(observer, "OUTPUT", output)
    monkeypatch.setattr(observer, "HOST_UNITS", {})
    monkeypatch.setattr(observer, "WORKFLOW_TARGETS", {})
    monkeypatch.setattr(
        observer,
        "collect_aws",
        lambda: [{"application": "example", "state": "observer-unavailable"}],
    )
    monkeypatch.setattr(observer, "collect_endpoints", lambda: [])
    observer.main()
    result = json.loads(output.read_text())
    assert result["observations"] == [
        {"application": "example", "state": "observer-unavailable"}
    ]
    assert not list(tmp_path.glob(".application-observations-*"))
