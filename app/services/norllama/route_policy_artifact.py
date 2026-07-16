from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_ROUTE_POLICY_ARTIFACT_PATH = Path("/var/lib/norman/norllama/route_policy.json")
ROUTE_POLICY_ARTIFACT_PATH_ENV = "NORMAN_NORLLAMA_ROUTE_POLICY_PATH"
ROUTE_POLICY_SCHEMA = "norman.norllama.route-policy.v1"
ROUTE_POLICY_VALIDATION_SCHEMA = "norman.norllama.route-policy-validation.v1"
ROUTE_POLICY_AUTHORIZATION_SCHEMA = "norman.norllama.route-policy-authorization.v1"
ROUTE_POLICY_BLOCK_SCHEMA = "norman.norllama.policy-block.v1"
ROUTE_POLICY_VERSION = "2026.07.13.lifecycle-v2"
SUPPORTED_ROUTE_POLICY_VERSIONS = {ROUTE_POLICY_VERSION}
DEFAULT_MAX_TTL_SECONDS = 7 * 24 * 60 * 60
EXPIRING_SOON_SECONDS = 72 * 60 * 60
MANUAL_DEGRADED_MAX_TTL_SECONDS = 6 * 60 * 60

AUTHORITY_FIELD_NAMES = frozenset(
    {
        "route_policy_id",
        "route_policy_hash",
        "route_policy_lifecycle",
        "route_policy_artifact",
        "policy_authority",
        "placement_policy",
        "residency_policy",
        "fallback_policy",
        "cloud_policy",
        "server_route_authority",
    }
)

_GENERATED_DEFAULT_ARTIFACT: dict[str, Any] | None = None


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_datetime(value: Any) -> datetime | None:
    clean = _clean(value)
    if not clean:
        return None
    if clean.endswith("Z"):
        clean = f"{clean[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(clean)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _artifact_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path:
        return Path(path)
    configured = _clean(os.environ.get(ROUTE_POLICY_ARTIFACT_PATH_ENV))
    return Path(configured) if configured else DEFAULT_ROUTE_POLICY_ARTIFACT_PATH


def _canonical_json_bytes(policy: dict[str, Any]) -> bytes:
    payload = dict(policy or {})
    payload.pop("policy_hash", None)
    payload.pop("policy_id", None)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def compute_route_policy_hash(policy: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(policy)).hexdigest()


def policy_id_for(version: str, policy_hash: str) -> str:
    return f"{_clean(version)}:{_clean(policy_hash)[:12]}"


def _source_hash(value: str) -> str:
    return hashlib.sha256(_clean(value).encode("utf-8")).hexdigest()


def _base_policy_material() -> dict[str, Any]:
    from app.services.norllama import route_policy as route_policy_module

    return route_policy_module._route_policy_contract_base()


def generate_route_policy_artifact(
    *,
    now: datetime | None = None,
    expires_at: datetime | None = None,
    benchmark_packet_ids: list[str] | None = None,
    benchmark_packet_hashes: list[str] | None = None,
    capability_packet_ids: list[str] | None = None,
    capability_packet_hashes: list[str] | None = None,
    generation: int = 1,
) -> dict[str, Any]:
    """Generate a canonical route-policy artifact from the compiled policy material."""

    current = (now or _now()).astimezone(timezone.utc)
    expiry = expires_at or current + timedelta(seconds=DEFAULT_MAX_TTL_SECONDS)
    material = _base_policy_material()
    benchmark_ids = benchmark_packet_ids or ["uplink-route-proof-active"]
    capability_ids = capability_packet_ids or ["norman-capability-canary-active"]
    benchmark_hashes = benchmark_packet_hashes or [
        _source_hash(packet_id) for packet_id in benchmark_ids
    ]
    capability_hashes = capability_packet_hashes or [
        _source_hash(packet_id) for packet_id in capability_ids
    ]
    artifact: dict[str, Any] = {
        "schema": ROUTE_POLICY_SCHEMA,
        "version": ROUTE_POLICY_VERSION,
        "issued_at": _iso(current),
        "compiled_at": _iso(current),
        "not_before": _iso(current),
        "expires_at": _iso(expiry),
        "max_ttl_seconds": DEFAULT_MAX_TTL_SECONDS,
        "refresh_generation": max(1, int(generation or 1)),
        "benchmark_packet_ids": list(benchmark_ids),
        "benchmark_packet_hashes": list(benchmark_hashes),
        "capability_packet_ids": list(capability_ids),
        "capability_packet_hashes": list(capability_hashes),
        "local_first": bool(material.get("local_first", True)),
        "allow_cloud_proxy": bool(material.get("allow_cloud_proxy", False)),
        "allow_cloud_tool_proxy": bool(material.get("allow_cloud_tool_proxy", False)),
        "escalation_policy": material.get("escalation_policy", "explicit_cloud_only"),
        "cost_posture": material.get("cost_posture", "local_token_first"),
        "planner": material.get("planner", "norllama"),
        "model_proxy": material.get("model_proxy", "norllama"),
        "model_selection": material.get("model_selection", "warm_policy"),
        "models": dict(material.get("models") or {}),
        "lanes": dict(material.get("lanes") or {}),
        "benchmark_gates": dict(material.get("benchmark_gates") or {}),
        "capability_gates": dict(material.get("capability_gates") or {}),
        "placement": dict(material.get("placement") or {}),
        "residency": dict(material.get("residency") or {}),
        "fallbacks": dict(material.get("fallbacks") or {}),
        "cloud_policy": dict(material.get("cloud_policy") or {}),
        "lifecycle_policy": dict(material.get("lifecycle_policy") or {}),
        "emergency_overlays": dict(material.get("emergency_overlays") or {}),
    }
    policy_hash = compute_route_policy_hash(artifact)
    artifact["policy_hash"] = policy_hash
    artifact["policy_id"] = policy_id_for(ROUTE_POLICY_VERSION, policy_hash)
    return artifact


@dataclass(frozen=True)
class RoutePolicyValidation:
    state: str
    integrity_valid: bool
    default_route_allowed: bool
    production_route_eligible: bool
    reason: str
    policy_id: str = ""
    policy_hash: str = ""
    issued_at: str = ""
    not_before: str = ""
    expires_at: str = ""
    seconds_to_expiry: int | None = None
    refresh_generation: int = 0
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": ROUTE_POLICY_VALIDATION_SCHEMA,
            "state": self.state,
            "integrity_valid": self.integrity_valid,
            "default_route_allowed": self.default_route_allowed,
            "production_route_eligible": self.production_route_eligible,
            "reason": self.reason,
            "policy_id": self.policy_id,
            "policy_hash": self.policy_hash,
            "issued_at": self.issued_at,
            "not_before": self.not_before,
            "expires_at": self.expires_at,
            "seconds_to_expiry": self.seconds_to_expiry,
            "refresh_generation": self.refresh_generation,
            "warnings": list(self.warnings),
        }


def _invalid_state(
    state: str,
    reason: str,
    policy: dict[str, Any] | None = None,
    *,
    policy_hash: str = "",
    warnings: list[str] | None = None,
) -> RoutePolicyValidation:
    policy = policy or {}
    return RoutePolicyValidation(
        state=state,
        integrity_valid=False,
        default_route_allowed=False,
        production_route_eligible=False,
        reason=reason,
        policy_id=_clean(policy.get("policy_id")),
        policy_hash=policy_hash or _clean(policy.get("policy_hash")),
        issued_at=_clean(policy.get("issued_at")),
        not_before=_clean(policy.get("not_before")),
        expires_at=_clean(policy.get("expires_at")),
        refresh_generation=int(policy.get("refresh_generation") or 0),
        warnings=tuple(warnings or ()),
    )


def validate_route_policy_artifact(
    policy: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate policy integrity before lifecycle and return an explicit state."""

    if not isinstance(policy, dict):
        return _invalid_state("invalid_schema", "policy_artifact_not_object").as_dict()
    if policy.get("schema") != ROUTE_POLICY_SCHEMA:
        return _invalid_state("invalid_schema", "unsupported_schema", policy).as_dict()
    version = _clean(policy.get("version"))
    if version not in SUPPORTED_ROUTE_POLICY_VERSIONS:
        return _invalid_state(
            "unsupported_version", "unsupported_version", policy
        ).as_dict()
    actual_hash = compute_route_policy_hash(policy)
    expected_hash = _clean(policy.get("policy_hash"))
    if not expected_hash or expected_hash != actual_hash:
        return _invalid_state(
            "invalid_hash",
            "policy_hash_mismatch",
            policy,
            policy_hash=actual_hash,
        ).as_dict()
    expected_policy_id = policy_id_for(version, actual_hash)
    if _clean(policy.get("policy_id")) != expected_policy_id:
        return _invalid_state(
            "invalid_policy_id",
            "policy_id_mismatch",
            policy,
            policy_hash=actual_hash,
        ).as_dict()

    issued_at = _coerce_datetime(policy.get("issued_at"))
    not_before = _coerce_datetime(policy.get("not_before"))
    expires_at = _coerce_datetime(policy.get("expires_at"))
    if issued_at is None:
        return _invalid_state("invalid_ttl", "invalid_issued_at", policy).as_dict()
    if not_before is None:
        return _invalid_state("invalid_ttl", "invalid_not_before", policy).as_dict()
    if expires_at is None:
        return _invalid_state("invalid_ttl", "invalid_expires_at", policy).as_dict()
    if expires_at <= issued_at:
        return _invalid_state(
            "invalid_ttl", "expires_at_not_after_issued_at", policy
        ).as_dict()
    max_ttl_seconds = int(policy.get("max_ttl_seconds") or 0)
    if max_ttl_seconds <= 0:
        return _invalid_state(
            "invalid_ttl", "invalid_max_ttl_seconds", policy
        ).as_dict()
    ttl_seconds = int((expires_at - issued_at).total_seconds())
    if ttl_seconds > max_ttl_seconds or ttl_seconds > DEFAULT_MAX_TTL_SECONDS:
        return _invalid_state("invalid_ttl", "ttl_exceeds_maximum", policy).as_dict()

    warnings: list[str] = []
    for id_key, hash_key in (
        ("benchmark_packet_ids", "benchmark_packet_hashes"),
        ("capability_packet_ids", "capability_packet_hashes"),
    ):
        ids = policy.get(id_key)
        hashes = policy.get(hash_key)
        if not isinstance(ids, list) or not ids:
            return _invalid_state(
                "invalid_schema", f"missing_{id_key}", policy
            ).as_dict()
        if not isinstance(hashes, list) or len(hashes) != len(ids):
            return _invalid_state(
                "invalid_schema", f"missing_{hash_key}", policy
            ).as_dict()
        if not all(_clean(value) for value in ids) or not all(
            _clean(value) for value in hashes
        ):
            return _invalid_state(
                "invalid_schema", f"empty_{id_key}_or_{hash_key}", policy
            ).as_dict()

    for key in (
        "models",
        "lanes",
        "placement",
        "residency",
        "fallbacks",
        "cloud_policy",
        "lifecycle_policy",
    ):
        if not isinstance(policy.get(key), dict) or not policy.get(key):
            return _invalid_state("invalid_schema", f"missing_{key}", policy).as_dict()

    current = (now or _now()).astimezone(timezone.utc)
    if current < not_before:
        return RoutePolicyValidation(
            state="not_yet_valid",
            integrity_valid=True,
            default_route_allowed=False,
            production_route_eligible=False,
            reason="policy_not_before_not_satisfied",
            policy_id=_clean(policy.get("policy_id")),
            policy_hash=actual_hash,
            issued_at=_iso(issued_at),
            not_before=_iso(not_before),
            expires_at=_iso(expires_at),
            seconds_to_expiry=int((expires_at - current).total_seconds()),
            refresh_generation=int(policy.get("refresh_generation") or 0),
            warnings=tuple(warnings),
        ).as_dict()
    seconds_to_expiry = int((expires_at - current).total_seconds())
    if seconds_to_expiry <= 0:
        return RoutePolicyValidation(
            state="expired_blocked",
            integrity_valid=True,
            default_route_allowed=False,
            production_route_eligible=False,
            reason="policy_expired",
            policy_id=_clean(policy.get("policy_id")),
            policy_hash=actual_hash,
            issued_at=_iso(issued_at),
            not_before=_iso(not_before),
            expires_at=_iso(expires_at),
            seconds_to_expiry=seconds_to_expiry,
            refresh_generation=int(policy.get("refresh_generation") or 0),
            warnings=tuple(warnings),
        ).as_dict()
    state = "expiring_soon" if seconds_to_expiry <= EXPIRING_SOON_SECONDS else "valid"
    if state == "expiring_soon":
        warnings.append("policy_expiring_soon")
    return RoutePolicyValidation(
        state=state,
        integrity_valid=True,
        default_route_allowed=True,
        production_route_eligible=True,
        reason="policy_valid" if state == "valid" else "policy_near_expiry",
        policy_id=_clean(policy.get("policy_id")),
        policy_hash=actual_hash,
        issued_at=_iso(issued_at),
        not_before=_iso(not_before),
        expires_at=_iso(expires_at),
        seconds_to_expiry=seconds_to_expiry,
        refresh_generation=int(policy.get("refresh_generation") or 0),
        warnings=tuple(warnings),
    ).as_dict()


def load_route_policy_artifact(
    path: str | os.PathLike[str] | None = None,
    *,
    now: datetime | None = None,
    allow_missing_default: bool = True,
) -> dict[str, Any]:
    artifact_path = _artifact_path(path)
    if artifact_path.exists():
        try:
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            artifact = {
                "schema": ROUTE_POLICY_SCHEMA,
                "version": ROUTE_POLICY_VERSION,
                "policy_id": "",
                "policy_hash": "",
                "load_error": _clean(exc),
            }
            validation = _invalid_state(
                "refresh_failed",
                "policy_artifact_load_failed",
                artifact,
            ).as_dict()
            return {
                "artifact": artifact,
                "validation": validation,
                "path": str(artifact_path),
                "source": "load_failed",
            }
        validation = validate_route_policy_artifact(artifact, now=now)
        return {
            "artifact": artifact,
            "validation": validation,
            "path": str(artifact_path),
            "source": "file",
        }
    if not allow_missing_default:
        artifact = {
            "schema": ROUTE_POLICY_SCHEMA,
            "version": ROUTE_POLICY_VERSION,
            "policy_id": "",
            "policy_hash": "",
            "path": str(artifact_path),
        }
        return {
            "artifact": artifact,
            "validation": _invalid_state(
                "refresh_failed",
                "policy_artifact_missing",
                artifact,
            ).as_dict(),
            "path": str(artifact_path),
            "source": "missing",
        }
    global _GENERATED_DEFAULT_ARTIFACT
    if _GENERATED_DEFAULT_ARTIFACT is None:
        _GENERATED_DEFAULT_ARTIFACT = generate_route_policy_artifact(now=now)
    artifact = dict(_GENERATED_DEFAULT_ARTIFACT)
    return {
        "artifact": artifact,
        "validation": validate_route_policy_artifact(artifact, now=now),
        "path": str(artifact_path),
        "source": "generated_default",
    }


def write_route_policy_artifact(
    artifact: dict[str, Any],
    path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    validation = validate_route_policy_artifact(artifact)
    if validation.get("state") not in {"valid", "expiring_soon"}:
        raise ValueError(f"invalid route policy artifact: {validation.get('reason')}")
    artifact_path = _artifact_path(path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = artifact_path.with_name(
        f".{artifact_path.name}.{os.getpid()}.{int(time.time() * 1000)}.tmp"
    )
    data = json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    with tmp_path.open("w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, artifact_path)
    directory_fd = os.open(str(artifact_path.parent), os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return {
        "schema": "norman.norllama.route-policy-write.v1",
        "path": str(artifact_path),
        "policy_id": artifact.get("policy_id"),
        "policy_hash": artifact.get("policy_hash"),
        "validation": validation,
    }


def refresh_route_policy_artifact(
    path: str | os.PathLike[str] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    refresh_started = (now or _now()).astimezone(timezone.utc)
    current = load_route_policy_artifact(path, now=refresh_started)
    current_artifact = (
        current.get("artifact") if isinstance(current.get("artifact"), dict) else {}
    )
    current_validation = (
        current.get("validation") if isinstance(current.get("validation"), dict) else {}
    )
    generation = int(current_artifact.get("refresh_generation") or 0) + 1
    artifact = generate_route_policy_artifact(
        now=refresh_started,
        generation=generation,
    )
    try:
        write_result = write_route_policy_artifact(artifact, path)
    except Exception as exc:
        preserved = load_route_policy_artifact(path, now=refresh_started)
        preserved_artifact = (
            preserved.get("artifact")
            if isinstance(preserved.get("artifact"), dict)
            else current_artifact
        )
        preserved_validation = (
            preserved.get("validation")
            if isinstance(preserved.get("validation"), dict)
            else current_validation
        )
        preserved_expiry = _coerce_datetime(preserved_artifact.get("expires_at"))
        return {
            "schema": "norman.norllama.route-policy-refresh.v1",
            "active_generation": int(preserved_artifact.get("refresh_generation") or 0),
            "previous_generation": int(current_artifact.get("refresh_generation") or 0),
            "last_refresh_attempt": _iso(refresh_started),
            "last_refresh_success": "",
            "last_refresh_error": f"{type(exc).__name__}: {exc}",
            "next_refresh_at": _iso(
                (preserved_expiry or refresh_started)
                - timedelta(seconds=EXPIRING_SOON_SECONDS)
            ),
            "write": {
                "schema": "norman.norllama.route-policy-write.v1",
                "ok": False,
                "path": str(_artifact_path(path)),
                "error": f"{type(exc).__name__}: {exc}",
            },
            "policy": preserved_artifact,
            "validation": preserved_validation,
        }
    return {
        "schema": "norman.norllama.route-policy-refresh.v1",
        "active_generation": artifact.get("refresh_generation"),
        "previous_generation": int(current_artifact.get("refresh_generation") or 0),
        "last_refresh_attempt": _iso(refresh_started),
        "last_refresh_success": _iso(refresh_started),
        "last_refresh_error": "",
        "next_refresh_at": _iso(
            (_coerce_datetime(artifact.get("expires_at")) or _now())
            - timedelta(seconds=EXPIRING_SOON_SECONDS)
        ),
        "write": write_result,
        "policy": artifact,
        "validation": write_result.get("validation", {}),
    }


def active_route_policy_identity(
    path: str | os.PathLike[str] | None = None,
    *,
    now: datetime | None = None,
    allow_missing_default: bool = True,
) -> dict[str, Any]:
    loaded = load_route_policy_artifact(
        path,
        now=now,
        allow_missing_default=allow_missing_default,
    )
    artifact = (
        loaded.get("artifact") if isinstance(loaded.get("artifact"), dict) else {}
    )
    validation = (
        loaded.get("validation") if isinstance(loaded.get("validation"), dict) else {}
    )
    return {
        "schema": "norman.norllama.route-policy-identity.v1",
        "policy_id": _clean(artifact.get("policy_id")),
        "policy_hash": _clean(artifact.get("policy_hash")),
        "version": _clean(artifact.get("version")),
        "path": _clean(loaded.get("path")),
        "source": _clean(loaded.get("source")),
        "lifecycle_state": _clean(validation.get("state")),
        "integrity_valid": bool(validation.get("integrity_valid")),
        "default_route_allowed": bool(validation.get("default_route_allowed")),
        "production_route_eligible": bool(validation.get("production_route_eligible")),
        "issued_at": _clean(artifact.get("issued_at")),
        "not_before": _clean(artifact.get("not_before")),
        "expires_at": _clean(artifact.get("expires_at")),
        "refresh_generation": int(artifact.get("refresh_generation") or 0),
        "validation": validation,
    }


def _manual_degraded_valid(
    value: dict[str, Any] | None, *, now: datetime
) -> tuple[bool, str]:
    if not isinstance(value, dict):
        return False, "manual_degraded_authorization_missing"
    if not value.get("manual_degraded_authorized"):
        return False, "manual_degraded_authorized_false"
    required = (
        "authorization_id",
        "authorized_by",
        "authorization_reason",
        "authorization_created_at",
        "authorization_expires_at",
    )
    for field in required:
        if not _clean(value.get(field)):
            return False, f"missing_{field}"
    if value.get("cloud_allowed"):
        return False, "manual_degraded_cloud_not_allowed"
    created = _coerce_datetime(value.get("authorization_created_at"))
    expires = _coerce_datetime(value.get("authorization_expires_at"))
    if created is None or expires is None:
        return False, "manual_degraded_invalid_time"
    if expires <= now:
        return False, "manual_degraded_expired"
    if expires <= created:
        return False, "manual_degraded_invalid_ttl"
    if int((expires - created).total_seconds()) > MANUAL_DEGRADED_MAX_TTL_SECONDS:
        return False, "manual_degraded_ttl_too_long"
    return True, "manual_degraded_authorized"


def _manual_degraded_supported_for_mode(execution_mode: str) -> bool:
    """Manual degraded mode is for explicit local inference, not route warming."""

    mode = _clean(execution_mode).lower()
    blocked_fragments = (
        "model_selection",
        "selection",
        "prefetch",
        "warm-policy",
        "warm_policy",
        "resident-warmer",
        "resident_warmer",
        "warmer",
    )
    return not any(fragment in mode for fragment in blocked_fragments)


def authorize_route_under_policy(
    *,
    policy_artifact: dict[str, Any] | None = None,
    execution_mode: str = "",
    requested_provider: str = "",
    requested_model: str = "",
    requested_lane: str = "",
    manual_degraded_authorization: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or _now()).astimezone(timezone.utc)
    artifact = policy_artifact
    if artifact is None:
        artifact = load_route_policy_artifact(now=current).get("artifact")
    validation = validate_route_policy_artifact(artifact, now=current)
    provider = _clean(requested_provider).lower()
    mode = _clean(execution_mode).lower()
    cloud_requested = (
        provider
        in {
            "anthropic",
            "aws-bedrock",
            "aws_bedrock",
            "bedrock",
            "codex",
            "openai",
            "openai-direct",
            "openai_direct",
        }
        or "cloud" in mode
    )
    state = _clean(validation.get("state"))
    allowed = bool(
        validation.get("integrity_valid")
        and validation.get("default_route_allowed")
        and state in {"valid", "expiring_soon"}
    )
    reason = _clean(validation.get("reason")) or state or "policy_unknown"
    manual_degraded = False
    if not allowed:
        manual_ok, manual_reason = _manual_degraded_valid(
            manual_degraded_authorization,
            now=current,
        )
        manual_supported = _manual_degraded_supported_for_mode(mode)
        if manual_ok and not cloud_requested and manual_supported:
            allowed = True
            manual_degraded = True
            reason = manual_reason
        elif manual_ok and not manual_supported:
            reason = "manual_degraded_not_allowed_for_route_warming"
        elif manual_degraded_authorization:
            reason = manual_reason
    production_eligible = bool(
        allowed
        and not manual_degraded
        and validation.get("production_route_eligible")
        and not cloud_requested
    )
    return {
        "schema": ROUTE_POLICY_AUTHORIZATION_SCHEMA,
        "allowed": allowed,
        "production_route_eligible": production_eligible,
        "manual_degraded": manual_degraded,
        "manual_degraded_authorized": manual_degraded,
        "policy_id": _clean((artifact or {}).get("policy_id")),
        "policy_hash": _clean((artifact or {}).get("policy_hash")),
        "lifecycle_state": state,
        "integrity_valid": bool(validation.get("integrity_valid")),
        "default_route_allowed": bool(validation.get("default_route_allowed")),
        "reason": "policy_valid" if allowed and not manual_degraded else reason,
        "execution_mode": execution_mode,
        "requested_provider": requested_provider,
        "requested_model": requested_model,
        "requested_lane": requested_lane,
        "cloud_requested": cloud_requested,
        "policy_issued_at": _clean((artifact or {}).get("issued_at")),
        "policy_expires_at": _clean((artifact or {}).get("expires_at")),
        "policy_refresh_generation": int(
            (artifact or {}).get("refresh_generation") or 0
        ),
        "validation": validation,
        "manual_degraded_authorization": dict(manual_degraded_authorization or {})
        if manual_degraded
        else {},
    }


def policy_block_response(authorization: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": ROUTE_POLICY_BLOCK_SCHEMA,
        "status": "blocked",
        "error": "route_policy_blocked",
        "message": _clean(authorization.get("reason"))
        or "route policy blocked request",
        "policy_id": _clean(authorization.get("policy_id")),
        "policy_hash": _clean(authorization.get("policy_hash")),
        "policy_lifecycle_state": _clean(authorization.get("lifecycle_state")),
        "policy_integrity_valid": bool(authorization.get("integrity_valid")),
        "policy_default_route_allowed": bool(
            authorization.get("default_route_allowed")
        ),
        "production_route_eligible": False,
        "manual_degraded_authorized": bool(
            authorization.get("manual_degraded_authorized")
        ),
    }
