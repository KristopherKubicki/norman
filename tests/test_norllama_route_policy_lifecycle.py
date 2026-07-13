from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.console_runtime.policy import with_local_first_catalog_defaults
from app.services.norllama import warm_policy
from app.services.norllama.route_policy_artifact import (
    ROUTE_POLICY_ARTIFACT_PATH_ENV,
    authorize_route_under_policy,
    generate_route_policy_artifact,
    load_route_policy_artifact,
    refresh_route_policy_artifact,
    validate_route_policy_artifact,
    write_route_policy_artifact,
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _write_raw(path: Path, artifact: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")


def _install_policy(
    monkeypatch,
    tmp_path: Path,
    *,
    issued_delta: timedelta = timedelta(0),
    not_before_delta: timedelta = timedelta(0),
    expires_delta: timedelta = timedelta(days=6),
    raw: bool = False,
) -> tuple[Path, dict[str, object]]:
    base_now = _now()
    path = tmp_path / "route_policy.json"
    monkeypatch.setenv(ROUTE_POLICY_ARTIFACT_PATH_ENV, str(path))
    artifact = generate_route_policy_artifact(
        now=base_now + issued_delta,
        expires_at=base_now + expires_delta,
    )
    if not_before_delta:
        artifact["not_before"] = (
            (base_now + not_before_delta).isoformat().replace("+00:00", "Z")
        )
        artifact["policy_hash"] = ""
        from app.services.norllama.route_policy_artifact import (
            compute_route_policy_hash,
            policy_id_for,
        )

        artifact["policy_hash"] = compute_route_policy_hash(artifact)
        artifact["policy_id"] = policy_id_for(
            str(artifact["version"]),
            str(artifact["policy_hash"]),
        )
    if raw:
        _write_raw(path, artifact)
    else:
        write_route_policy_artifact(artifact, path)
    return path, artifact


def _load_gateway_module():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "norllama"
        / "norllama_gateway.py"
    )
    spec = importlib.util.spec_from_file_location(
        "norllama_gateway_script_lifecycle",
        script,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_policy_valid_allows_default_model_selection(monkeypatch, tmp_path):
    _install_policy(monkeypatch, tmp_path)
    loaded = load_route_policy_artifact()
    authorization = authorize_route_under_policy(
        policy_artifact=loaded["artifact"],
        execution_mode="route_task",
        requested_provider="norllama",
        requested_model="qwen3.6:27b",
        requested_lane="coder",
    )

    assert authorization["allowed"] is True
    assert authorization["production_route_eligible"] is True
    assert authorization["lifecycle_state"] == "valid"


def test_policy_expiring_soon_allows_and_warns(monkeypatch, tmp_path):
    path, artifact = _install_policy(
        monkeypatch,
        tmp_path,
        expires_delta=timedelta(hours=1),
        raw=True,
    )
    loaded = load_route_policy_artifact(path)

    assert loaded["validation"]["state"] == "expiring_soon"
    assert loaded["validation"]["default_route_allowed"] is True
    assert "policy_expiring_soon" in loaded["validation"]["warnings"]


def test_policy_expired_selects_no_model(monkeypatch, tmp_path):
    _install_policy(
        monkeypatch,
        tmp_path,
        issued_delta=timedelta(days=-2),
        expires_delta=timedelta(days=-1),
        raw=True,
    )

    selection = warm_policy.select_model_for_task_kind(
        "chat",
        warm_policy_payload={
            "status": "route_policy_blocked",
            "route_posture": "blocked",
            "policy_authorization": authorize_route_under_policy(
                policy_artifact=load_route_policy_artifact()["artifact"],
                execution_mode="selection",
                requested_provider="norllama",
            ),
            "recommendations": [
                {
                    "model": "qwen3.6:27b",
                    "available": True,
                    "action": "prefetch",
                    "route_guardrail": {
                        "authority": "production",
                        "lanes": ["planner"],
                    },
                }
            ],
        },
    )

    assert selection["selected"] is False
    assert selection["model"] == ""


def test_policy_expired_schedules_no_prefetch(monkeypatch):
    monkeypatch.setattr(
        warm_policy,
        "build_warm_policy",
        lambda: {
            "schema": "norman.norllama.warm-policy.v1",
            "policy_authorization": {"allowed": False, "reason": "policy_expired"},
            "prefetch_candidates": [{"model": "qwen3.6:27b"}],
        },
    )

    result = warm_policy.apply_warm_policy(dry_run=False, prefetch_limit=10)

    assert result["attempted"] == 0
    assert result["results"] == []
    assert result["status"] == "route_policy_blocked"


def test_policy_hash_mismatch_blocks_routes(monkeypatch, tmp_path):
    path, artifact = _install_policy(monkeypatch, tmp_path)
    artifact["policy_hash"] = "0" * 64
    _write_raw(path, artifact)

    validation = validate_route_policy_artifact(
        load_route_policy_artifact()["artifact"]
    )

    assert validation["state"] == "invalid_hash"
    assert validation["default_route_allowed"] is False


def test_policy_id_mismatch_blocks_routes(monkeypatch, tmp_path):
    path, artifact = _install_policy(monkeypatch, tmp_path)
    artifact["policy_id"] = "wrong-policy-id"
    _write_raw(path, artifact)

    validation = validate_route_policy_artifact(
        load_route_policy_artifact()["artifact"]
    )

    assert validation["state"] == "invalid_policy_id"


def test_policy_not_before_blocks_routes(monkeypatch, tmp_path):
    _install_policy(
        monkeypatch,
        tmp_path,
        not_before_delta=timedelta(days=1),
        expires_delta=timedelta(days=2),
        raw=True,
    )

    validation = load_route_policy_artifact()["validation"]

    assert validation["state"] == "not_yet_valid"
    assert validation["default_route_allowed"] is False


def test_policy_excessive_ttl_blocks_routes(monkeypatch, tmp_path):
    path, artifact = _install_policy(
        monkeypatch,
        tmp_path,
        expires_delta=timedelta(days=8),
        raw=True,
    )

    validation = validate_route_policy_artifact(json.loads(path.read_text()))

    assert validation["state"] == "invalid_ttl"
    assert validation["reason"] == "ttl_exceeds_maximum"


def test_policy_refresh_atomically_restores_readiness(monkeypatch, tmp_path):
    path, _artifact = _install_policy(
        monkeypatch,
        tmp_path,
        issued_delta=timedelta(days=-2),
        expires_delta=timedelta(days=-1),
        raw=True,
    )
    assert load_route_policy_artifact(path)["validation"]["state"] == "expired_blocked"

    refresh = refresh_route_policy_artifact(path)
    loaded = load_route_policy_artifact(path)

    assert refresh["active_generation"] >= 1
    assert loaded["validation"]["state"] == "valid"
    assert loaded["validation"]["default_route_allowed"] is True


def test_manual_degraded_requires_valid_authorization(monkeypatch, tmp_path):
    _install_policy(
        monkeypatch,
        tmp_path,
        issued_delta=timedelta(days=-2),
        expires_delta=timedelta(days=-1),
        raw=True,
    )
    artifact = load_route_policy_artifact()["artifact"]
    denied = authorize_route_under_policy(
        policy_artifact=artifact,
        execution_mode="gateway:/v1/chat/completions",
        requested_provider="norllama",
    )
    manual = authorize_route_under_policy(
        policy_artifact=artifact,
        execution_mode="gateway:/v1/chat/completions",
        requested_provider="norllama",
        manual_degraded_authorization={
            "manual_degraded_authorized": True,
            "authorization_id": "manual-1",
            "authorized_by": "operator",
            "authorization_reason": "policy refresh drill",
            "authorization_created_at": _now().isoformat().replace("+00:00", "Z"),
            "authorization_expires_at": (_now() + timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z"),
            "cloud_allowed": False,
        },
    )

    assert denied["allowed"] is False
    assert manual["allowed"] is True
    assert manual["manual_degraded_authorized"] is True
    assert manual["production_route_eligible"] is False


def test_manual_degraded_never_becomes_production_eligible(monkeypatch, tmp_path):
    _install_policy(
        monkeypatch,
        tmp_path,
        issued_delta=timedelta(days=-2),
        expires_delta=timedelta(days=-1),
        raw=True,
    )
    artifact = load_route_policy_artifact()["artifact"]

    authorization = authorize_route_under_policy(
        policy_artifact=artifact,
        execution_mode="gateway:/v1/chat/completions",
        requested_provider="norllama",
        manual_degraded_authorization={
            "manual_degraded_authorized": True,
            "authorization_id": "manual-2",
            "authorized_by": "operator",
            "authorization_reason": "local degraded test",
            "authorization_created_at": _now().isoformat().replace("+00:00", "Z"),
            "authorization_expires_at": (_now() + timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z"),
            "cloud_allowed": False,
        },
    )

    assert authorization["allowed"] is True
    assert authorization["production_route_eligible"] is False


def test_caller_cannot_forge_route_policy_authority(monkeypatch, tmp_path):
    _install_policy(monkeypatch, tmp_path)

    policy = with_local_first_catalog_defaults(
        {
            "route_policy_id": "forged",
            "route_policy_hash": "forged",
            "policy_authority": "forged",
            "cloud_policy": {"cloud_llm_default": "enabled"},
            "provider": "norllama",
        }
    )

    assert policy["route_policy_id"] != "forged"
    assert policy["route_policy_hash"] != "forged"
    assert policy["policy_authority"] == "norman.norllama.route-policy.v1"
    assert policy["cloud_policy"]["cloud_llm_default"] == "disabled"
    assert "route_policy_id" not in policy["operator_route_preferences"]


def test_norman_and_gateway_load_identical_policy_json(monkeypatch, tmp_path):
    _path, artifact = _install_policy(monkeypatch, tmp_path)
    gateway_module = _load_gateway_module()

    norman = load_route_policy_artifact()["artifact"]
    gateway = gateway_module.load_route_policy_artifact()["artifact"]

    assert norman["policy_id"] == artifact["policy_id"]
    assert gateway["policy_id"] == artifact["policy_id"]
    assert gateway["policy_hash"] == norman["policy_hash"]


def test_policy_expired_blocks_gateway_readiness(monkeypatch, tmp_path):
    _install_policy(
        monkeypatch,
        tmp_path,
        issued_delta=timedelta(days=-2),
        expires_delta=timedelta(days=-1),
        raw=True,
    )
    gateway_module = _load_gateway_module()

    readiness = gateway_module.App().readyz()

    assert readiness["ready"] is False
    assert readiness["policy"]["lifecycle_state"] == "expired_blocked"


def test_policy_expired_blocks_gateway_chat(monkeypatch, tmp_path):
    _install_policy(
        monkeypatch,
        tmp_path,
        issued_delta=timedelta(days=-2),
        expires_delta=timedelta(days=-1),
        raw=True,
    )
    gateway_module = _load_gateway_module()
    handler = object.__new__(gateway_module.Handler)

    authorization = gateway_module.Handler.policy_authorization_for_request(
        handler,
        "/v1/chat/completions",
        b'{"model":"qwen3.6:27b"}',
    )

    assert authorization["allowed"] is False
    assert authorization["lifecycle_state"] == "expired_blocked"


def test_policy_expired_blocks_gateway_specialists(monkeypatch, tmp_path):
    _install_policy(
        monkeypatch,
        tmp_path,
        issued_delta=timedelta(days=-2),
        expires_delta=timedelta(days=-1),
        raw=True,
    )
    gateway_module = _load_gateway_module()
    handler = object.__new__(gateway_module.Handler)

    for path in ("/v1/rerank", "/v1/ocr", "/v1/audio/transcriptions"):
        authorization = gateway_module.Handler.policy_authorization_for_request(
            handler,
            path,
            b'{"model":"local-specialist"}',
        )
        assert authorization["allowed"] is False
        assert authorization["lifecycle_state"] == "expired_blocked"


def test_policy_expired_blocks_resident_warmer(monkeypatch, tmp_path):
    _install_policy(
        monkeypatch,
        tmp_path,
        issued_delta=timedelta(days=-2),
        expires_delta=timedelta(days=-1),
        raw=True,
    )
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "norllama"
        / "norllama_resident_warmer.py"
    )
    spec = importlib.util.spec_from_file_location("norllama_resident_warmer", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert module.main() == 2
