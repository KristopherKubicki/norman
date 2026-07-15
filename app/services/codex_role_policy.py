from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

SCHEMA = "norman.codex-role-policy.v1"
SUPPORTED_VERSIONS = {"2026.07.15.role-v1"}
ENV_PATH = "NORMAN_CODEX_ROLE_POLICY_PATH"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO_ROOT / "db" / "policies" / "codex_role_policy.json"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _canonical_bytes(policy: dict[str, Any]) -> bytes:
    payload = dict(policy)
    payload.pop("policy_hash", None)
    payload.pop("policy_id", None)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def compute_policy_hash(policy: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(policy)).hexdigest()


def policy_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path:
        return Path(path)
    configured = _clean(os.environ.get(ENV_PATH))
    return Path(configured) if configured else DEFAULT_PATH


def load_codex_role_policy(
    path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    artifact_path = policy_path(path)
    policy = json.loads(artifact_path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict):
        raise ValueError("Codex role policy must be a JSON object")
    if policy.get("schema") != SCHEMA:
        raise ValueError("Codex role policy schema is unsupported")
    version = _clean(policy.get("version"))
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"Codex role policy version is unsupported: {version}")
    if not isinstance(policy.get("roles"), dict) or not policy["roles"]:
        raise ValueError("Codex role policy must define roles")
    if not isinstance(policy.get("switchable_models"), dict):
        raise ValueError("Codex role policy must define switchable_models")
    identity_hash = compute_policy_hash(policy)
    declared_hash = _clean(policy.get("policy_hash"))
    if declared_hash and declared_hash != identity_hash:
        raise ValueError("Codex role policy hash mismatch")
    declared_id = _clean(policy.get("policy_id"))
    identity_id = f"{version}:{identity_hash[:12]}"
    if declared_id and declared_id != identity_id:
        raise ValueError("Codex role policy ID mismatch")
    enriched = dict(policy)
    enriched["policy_hash"] = identity_hash
    enriched["policy_id"] = identity_id
    enriched["artifact_path"] = str(artifact_path)
    return enriched


def _role(policy: dict[str, Any], role_name: str) -> dict[str, Any]:
    roles = policy.get("roles") if isinstance(policy.get("roles"), dict) else {}
    role = roles.get(role_name)
    if not isinstance(role, dict):
        raise KeyError(f"missing Codex role policy role: {role_name}")
    return role


def codex_role_value(
    role_name: str,
    key: str,
    default: str = "",
    *,
    policy: dict[str, Any] | None = None,
) -> str:
    active = policy or load_codex_role_policy()
    value = _role(active, role_name).get(key)
    return _clean(value) or default


def codex_switchable_models(
    scope: str,
    *,
    policy: dict[str, Any] | None = None,
) -> str:
    active = policy or load_codex_role_policy()
    switchable = active.get("switchable_models")
    if not isinstance(switchable, dict):
        return ""
    models = switchable.get(scope)
    if not isinstance(models, list):
        return ""
    return ",".join(_clean(model) for model in models if _clean(model))


def codex_role_policy_identity(
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, str]:
    active = policy or load_codex_role_policy()
    return {
        "schema": SCHEMA,
        "policy_id": _clean(active.get("policy_id")),
        "policy_hash": _clean(active.get("policy_hash")),
        "version": _clean(active.get("version")),
        "artifact_path": _clean(active.get("artifact_path")),
    }
