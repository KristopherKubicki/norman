import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.norllama import route_policy
from scripts.gateway_routing_snapshot import snapshot
from scripts.norllama import resident_prefetch as prefetch
from scripts.norllama import norllama_resident_warmer as warmer


def test_named_model_cannot_silently_switch_families():
    policy = {
        "explicit_cloud_models": {
            "norman-code-sol": {
                "model": "openai.gpt-6-astra",
                "provider": "aws-bedrock",
                "lane": "coder",
            }
        }
    }
    assert (
        route_policy.explicit_cloud_selection_for_model(
            "norman-code-sol", cloud_policy=policy
        )
        is None
    )
    policy["explicit_cloud_models"]["norman-code-sol"]["model"] = "openai.gpt-5.6-sol"
    assert (
        route_policy.explicit_cloud_selection_for_model(
            "norman-code-sol", cloud_policy=policy
        )["model"]
        == "openai.gpt-5.6-sol"
    )


def test_compiler_does_not_publish_misnamed_aliases(monkeypatch):
    rows = {
        role: {
            "model": "gpt-6-astra",
            "provider": "openai",
            "aliases": ["norman-code-sol", "gpt-6-astra"],
        }
        for role in ("economy", "authority", "frontier")
    }
    monkeypatch.setattr(route_policy, "MODEL_ROLES", rows)
    result = route_policy._explicit_cloud_models()
    assert "norman-code-sol" not in result
    assert result["gpt-6-astra"]["model"] == "gpt-6-astra"


def test_snapshot_never_exports_credentials_or_identity_material():
    registry = {
        "schema": "norman.aws-account-routing.v1",
        "bindings": {
            "work": {
                "owner": "work",
                "regions": ["us-west-2"],
                "credential_alias": "secret-alias",
                "account_id": "123456789012",
                "principal_arn": "private-principal",
            }
        },
        "gateway_routes": {"work": "work"},
    }
    policy = {
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "cloud_policy": {
            "explicit_cloud_models": {
                "norman-code-astra": {
                    "model": "openai.gpt-6-astra",
                    "provider": "aws-bedrock",
                    "secret": "hidden",
                }
            }
        },
    }
    result = snapshot(registry, policy)
    rendered = json.dumps(result)
    assert all(
        value not in rendered
        for value in ("secret-alias", "123456789012", "private-principal", "hidden")
    )
    assert result["routes"]["work"]["owner"] == "work"
    assert result["execution_identity_verified"] is False
    registry["gateway_routes"]["work"] = "unregistered"
    with pytest.raises(KeyError):
        snapshot(registry, policy)


@pytest.fixture
def worker(monkeypatch):
    model = "qwen3.8:27b"
    docs = {
        "/readyz": {"ready": True, "policy": {"production_route_eligible": True}},
        "/v1/warm-policy": {
            "policy_authorization": {"allowed": True},
            "route_policy": {"models": {"router": model}},
            "route_guardrails": {"lanes": {"coder": {"status": "unknown"}}},
        },
        "/v1/models": {
            "data": [
                {"id": model, "provider": "ollama", "hosts": ["http://127.0.0.1:11434"]}
            ]
        },
        "/api/ps": {"models": [{"model": model}]},
    }
    calls = []

    def request(base, path, payload=None):
        calls.append((base, path, payload))
        return docs[path]

    monkeypatch.setattr(prefetch, "request", request)
    topology = {
        "workers": {"spark-151": {"address": "192.168.42.151", "gateway_port": 18151}}
    }
    return docs, calls, topology


def test_residency_does_not_grant_task_authority(worker):
    docs, calls, topology = worker
    result = prefetch.run("work", topology, {})
    assert result["status"] == "resident"
    assert result["task_admission"]["coder"] == "unknown"
    assert all(
        base == "http://192.168.42.151:18151" and payload is None
        for base, path, payload in calls
    )


def test_work_model_cannot_prefetch_on_personal_worker(worker):
    docs, calls, topology = worker
    docs["/v1/models"]["data"][0]["hosts"] = ["http://192.168.40.150:11435"]
    result = prefetch.run("work", topology, {}, warm_now=True)
    assert result["status"] == "unavailable"
    assert all(payload is None for base, path, payload in calls)


def test_cold_model_is_not_loaded_without_capacity_decision(worker):
    docs, calls, topology = worker
    docs["/api/ps"]["models"] = []
    assert prefetch.run("work", topology, {}, warm_now=True)["status"] == "cold"


@pytest.mark.parametrize("attempts", [[1000], [900, 850, 800, 750, 700, 650], [5000]])
def test_failed_or_future_attempts_keep_renewal_bounded(worker, monkeypatch, attempts):
    docs, calls, topology = worker
    monkeypatch.setattr(prefetch.time, "time", lambda: 1100)
    assert (
        prefetch.run("work", topology, {"attempts": attempts}, warm_now=True)["status"]
        == "cooldown"
    )


def test_policy_blocks_even_an_already_loaded_model(worker):
    docs, calls, topology = worker
    docs["/v1/warm-policy"]["policy_authorization"]["allowed"] = False
    assert prefetch.run("work", topology, {}, warm_now=True)["status"] == "unavailable"


def test_prefetch_verifies_job_identity_and_residency(worker, monkeypatch):
    docs, calls, topology = worker
    observed = prefetch.observe("work", topology)
    docs["/v1/prefetch"] = {"job_id": "ours"}
    docs["/v1/prefetch/status?job_id=ours"] = {
        "items": [
            {"job_id": "other", "status": "failed"},
            {"job_id": "ours", "status": "warm"},
        ]
    }
    assert prefetch.prefetch(observed)["resident_verified"] is True
    docs["/api/ps"]["models"] = []
    with pytest.raises(ValueError, match="without observed residency"):
        prefetch.prefetch(observed)


def test_nonterminal_prefetch_is_reported_as_timeout(monkeypatch):
    moments = iter([0, 0.5, 2])
    monkeypatch.setattr(warmer.time, "monotonic", lambda: next(moments))
    monkeypatch.setattr(warmer.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        warmer,
        "_json_request",
        lambda *a, **k: (200, {"items": [{"status": "running"}]}),
    )
    assert (
        warmer._poll_prefetch("http://localhost", "id", timeout_s=1)["status"]
        == "timeout"
    )


def test_old_warmer_does_not_load_with_unknown_memory(monkeypatch, capsys):
    monkeypatch.setenv("NORLLAMA_WARM_CHAT_MODELS", "qwen3.8:27b")
    monkeypatch.setenv("NORLLAMA_WARM_EMBED_MODELS", "")
    monkeypatch.setenv("NORLLAMA_WARM_MIN_FREE_MIB_CHAT", "18000")
    monkeypatch.setattr(
        warmer, "load_route_policy_artifact", lambda **k: {"artifact": {}}
    )
    monkeypatch.setattr(
        warmer, "authorize_route_under_policy", lambda **k: {"allowed": True}
    )
    monkeypatch.setattr(warmer, "_free_mib", lambda *a: None)
    monkeypatch.setattr(
        warmer, "_warm_chat_model", lambda **k: pytest.fail("must not load")
    )
    assert warmer.main() == 1
    assert (
        json.loads(capsys.readouterr().out)["results"][0]["status"]
        == "skipped_unknown_gpu_memory"
    )


def test_attempt_is_persisted_before_submission_and_failure_is_bounded(
    worker, monkeypatch, tmp_path
):
    import sys

    docs, calls, topology = worker
    config = tmp_path / "topology.json"
    config.write_text(json.dumps(topology))
    state = tmp_path / "state.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prefetch",
            "--scope",
            "work",
            "--topology",
            str(config),
            "--state",
            str(state),
            "--warm-now",
        ],
    )
    submitted = []

    def fail(observation):
        assert len(json.loads(state.read_text())["attempts"]) == 1
        submitted.append(True)
        raise OSError("worker unavailable")

    monkeypatch.setattr(prefetch, "prefetch", fail)
    assert prefetch.main() == 1
    assert prefetch.main() == 0
    assert submitted == [True]
    assert json.loads(state.read_text())["status"] == "cooldown"


def test_route_snapshot_wrapper_rejects_shell_injection():
    import subprocess

    wrapper = Path(__file__).parents[1] / "scripts/codex_route_policy.sh"
    result = subprocess.run(
        ["bash", str(wrapper), "--route", "work; echo unsafe"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert result.stdout == ""
