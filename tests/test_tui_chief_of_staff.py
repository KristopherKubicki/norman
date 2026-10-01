from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit


def _load(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "tui_chief_of_staff", scripts / "tui_chief_of_staff.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_chief_of_staff"] = module
    spec.loader.exec_module(module)
    return module


def _health(now: datetime) -> dict:
    return {
        "checked_at": now.isoformat().replace("+00:00", "Z"),
        "status": "ok",
        "hosts": [
            {
                "host": "hal",
                "active_count": 2,
                "expected_count": 2,
                "fail_count": 0,
                "warn_count": 0,
            },
            {
                "host": "private-host",
                "active_count": 1,
                "expected_count": 1,
                "fail_count": 0,
                "warn_count": 0,
            },
        ],
        "issues": [],
    }


def _proof(now: datetime) -> dict:
    return {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "summary": {"passed": 2, "failed": 0},
        "results": [
            {
                "target": "norman",
                "host": "norman",
                "passed": True,
                "outcome": "deterministic_status",
                "final": {"local_planner_readiness": {"ready": True}},
            }
        ],
    }


def _topology(*, runtime_workers: list[str] | None = None) -> dict:
    return {
        "resident_pool": {
            "scheduler_workers": ["spark-a", "spark-b"],
            "runtime_workers": runtime_workers or ["spark-a", "spark-b"],
            "minimum_runtime_replicas": 2,
        }
    }


def test_compact_packet_tracks_coverage_and_freshness(monkeypatch) -> None:
    module = _load(monkeypatch)
    now = datetime(2026, 8, 16, 15, 0, tzinfo=timezone.utc)

    packet = module.compact_packet(
        _health(now), _proof(now), now=now, topology=_topology()
    )

    assert packet["fleet"]["active"] == 3
    assert packet["fleet"]["expected"] == 3
    assert packet["fleet"]["coverage_complete"] is True
    assert packet["stale_sources"] == []


def test_compact_packet_accepts_epoch_proof_time_and_omits_zero_count_reports(
    monkeypatch,
) -> None:
    module = _load(monkeypatch)
    now = datetime(2026, 8, 16, 15, 0, tzinfo=timezone.utc)
    health = _health(now)
    health["hosts"].append(
        {
            "host": "norman",
            "active_count": 0,
            "expected_count": 0,
            "fail_count": 0,
            "warn_count": 0,
        }
    )
    proof = _proof(now)
    proof["generated_at"] = int(now.timestamp())

    packet = module.compact_packet(health, proof, now=now)

    assert packet["route_proof"]["age_seconds"] == 0
    assert len(packet["fleet"]["hosts"]) == 2


def test_packet_signature_ignores_observation_age(monkeypatch) -> None:
    module = _load(monkeypatch)
    now = datetime(2026, 8, 16, 15, 0, tzinfo=timezone.utc)
    first = module.compact_packet(_health(now), _proof(now), now=now)
    second = module.compact_packet(
        _health(now + timedelta(minutes=1)),
        _proof(now + timedelta(minutes=1)),
        now=now + timedelta(minutes=1),
    )

    assert module.packet_signature(first) == module.packet_signature(second)


def test_publish_on_change_or_heartbeat(monkeypatch) -> None:
    module = _load(monkeypatch)
    now = datetime(2026, 8, 16, 15, 0, tzinfo=timezone.utc)
    recent = (now - timedelta(minutes=30)).isoformat()
    old = (now - timedelta(hours=3)).isoformat()

    assert module.should_publish(
        signature="new",
        state={"last_published_signature": "old", "last_published_at": recent},
        now=now,
        heartbeat_seconds=7200,
    ) == (True, "material_change")
    assert module.should_publish(
        signature="same",
        state={"last_published_signature": "same", "last_published_at": old},
        now=now,
        heartbeat_seconds=7200,
    ) == (True, "heartbeat")
    assert module.should_publish(
        signature="same",
        state={"last_published_signature": "same", "last_published_at": recent},
        now=now,
        heartbeat_seconds=7200,
    ) == (False, "deduplicated")


def test_deterministic_brief_fails_visible_on_missing_coverage(monkeypatch) -> None:
    module = _load(monkeypatch)
    now = datetime(2026, 8, 16, 15, 0, tzinfo=timezone.utc)
    health = _health(now)
    health["hosts"][1]["active_count"] = 0

    brief = module.deterministic_brief(
        module.compact_packet(health, _proof(now), now=now)
    )

    assert brief["status"] == "attention"
    assert any("coverage" in item.lower() for item in brief["attention"])


def test_deterministic_brief_fails_visible_on_runtime_replica_deficit(
    monkeypatch,
) -> None:
    module = _load(monkeypatch)
    now = datetime(2026, 8, 16, 15, 0, tzinfo=timezone.utc)
    packet = module.compact_packet(
        _health(now),
        _proof(now),
        now=now,
        topology=_topology(runtime_workers=["spark-a"]),
    )

    brief = module.deterministic_brief(packet)

    assert brief["status"] == "attention"
    assert packet["resident_pool"]["scheduler_replicas"] == 2
    assert packet["resident_pool"]["runtime_replicas"] == 1
    assert any("runtime redundancy" in item.lower() for item in brief["attention"])


def test_deterministic_brief_flags_missing_planner_readiness(monkeypatch) -> None:
    module = _load(monkeypatch)
    now = datetime(2026, 8, 16, 15, 0, tzinfo=timezone.utc)
    proof = _proof(now)
    proof["results"][0]["final"]["local_planner_readiness"]["ready"] = False

    brief = module.deterministic_brief(
        module.compact_packet(_health(now), proof, now=now, topology=_topology())
    )

    assert brief["status"] == "attention"
    assert any("planner readiness" in item.lower() for item in brief["attention"])


def test_live_resident_pool_counts_only_healthy_model_hosts(monkeypatch) -> None:
    module = _load(monkeypatch)
    topology = _topology()
    topology["workers"] = {
        "spark-a": {
            "address": "spark-a",
            "resident_scheduler_port": 18161,
            "resident_runtime_port": 11435,
        },
        "spark-b": {
            "address": "spark-b",
            "resident_scheduler_port": 18161,
            "resident_runtime_port": 11435,
        },
    }

    class Response:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            import json

            return json.dumps(self.payload).encode()

    def fake_urlopen(request, timeout):
        assert timeout == 0.25
        parsed = urlsplit(request.full_url)
        if parsed.port == 18161:
            return Response({"ready": True})
        if parsed.hostname == "spark-a":
            return Response({"models": [{"name": "future-resident"}]})
        return Response({"models": [{"name": "different-model"}]})

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    status = module.live_resident_pool_status(
        topology,
        resident_model="future-resident",
        timeout=0.25,
    )

    assert status["scheduler_configured"] == 2
    assert status["scheduler_replicas"] == 2
    assert status["runtime_configured"] == 2
    assert status["runtime_replicas"] == 1
    assert status["runtime_redundant"] is False
    assert status["runtime_errors"] == {"spark-b": "resident_model_missing"}
