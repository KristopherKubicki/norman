"""Estate registry helpers for Norman's principal/bot/worker model.

This module loads a machine-readable seed registry that mirrors the higher-level
estate model in docs. The registry is intentionally light-weight for now: it is
not the final database schema, but it gives the app and future migration code a
stable source of truth for the first object vocabulary.
"""

from __future__ import annotations

import pathlib
import shutil
from typing import Any, Dict, Iterable

import yaml


_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = _ROOT / "db" / "estate" / "registry.yaml"
DEFAULT_TEMPLATE_PATH = _ROOT / "db" / "estate" / "registry.yaml.dist"

_SECTION_NAMES = (
    "principals",
    "policy_profiles",
    "control_classes",
    "domains",
    "places",
    "bots",
    "workers",
    "assets",
    "services",
    "channels",
    "people",
)

_REFERENCE_FIELDS = {
    "domains": ("principal", "default_policy_profile"),
    "places": ("principal",),
    "bots": ("principal", "domain", "policy_profile"),
    "workers": ("principal", "place", "control_class", "policy_profile"),
    "assets": ("principal", "place", "worker", "control_class"),
    "services": ("principal", "domain", "bot", "worker", "place", "policy_profile"),
    "channels": ("principal", "domain", "bot", "service", "policy_profile", "person"),
    "people": ("principal",),
}

_BBS_POLICY_SECTIONS = ("workers", "services")
_BBS_ROLES = {
    "broker",
    "root",
    "operator",
    "work",
    "personal",
    "network",
    "private",
    "yhix",
}
_BBS_ZONES = {"root", "global", "work", "personal", "network", "private", "yhix"}
_BBS_BOOL_FIELDS = {"receive", "full_coverage", "cross_zone", "allow_private"}
_BBS_CONNECTOR_FIELD_MAP = {
    "role": "bbs_acl_role",
    "zone": "bbs_zone",
    "receive": "bbs_receive",
    "channels": "bbs_channels",
    "full_coverage": "bbs_full_coverage",
    "cross_zone": "bbs_cross_zone",
    "allow_private": "bbs_allow_private",
}

POWER_CLASSES = ("mouth", "purse", "seal", "key", "sword")
POWER_LEVELS = {
    "none",
    "denied",
    "read",
    "draft",
    "limited",
    "scoped",
    "operator-approved",
    "emergency",
    "full",
}
_POWER_SECTIONS = (
    "policy_profiles",
    "bots",
    "workers",
    "assets",
    "services",
    "channels",
)
_INERT_POWER_LEVELS = {"none", "denied"}
_PENDING_REVOCATION_TEST_VALUES = {"", "never", "pending", "unknown", "untested"}
POWER_ENFORCEMENT_GATES = {
    "mouth": {
        "gate": "outbound send policy",
        "controls": ("BBS actor ACL", "Caddy/client allowlist", "channel send policy"),
    },
    "purse": {
        "gate": "spend authority",
        "controls": ("spend cap", "billing owner", "revocation test"),
    },
    "seal": {
        "gate": "approval authority",
        "controls": ("command approval", "merge/deploy policy", "audit log"),
    },
    "key": {
        "gate": "secret and system access",
        "controls": ("keyservice lease", "scoped credential", "revocation test"),
    },
    "sword": {
        "gate": "harm-capable authority",
        "controls": ("human owner", "accountable purpose", "panic lock"),
    },
}


class EstateRegistryError(RuntimeError):
    """Raised for invalid estate registry state."""


def _default_registry() -> Dict[str, list[dict[str, Any]]]:
    return {name: [] for name in _SECTION_NAMES}


def _slug_index(
    items: Iterable[dict[str, Any]], section: str
) -> Dict[str, dict[str, Any]]:
    index: Dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise EstateRegistryError(f"Section `{section}` entries must be mappings")
        slug = str(item.get("slug") or "").strip()
        if not slug:
            raise EstateRegistryError(
                f"Section `{section}` entries must include `slug`"
            )
        if slug in index:
            raise EstateRegistryError(f"Section `{section}` has duplicate slug: {slug}")
        index[slug] = item
    return index


def _validate_references(registry: Dict[str, list[dict[str, Any]]]) -> None:
    indexes = {name: _slug_index(registry[name], name) for name in _SECTION_NAMES}

    section_targets = {
        "principal": "principals",
        "default_policy_profile": "policy_profiles",
        "policy_profile": "policy_profiles",
        "control_class": "control_classes",
        "domain": "domains",
        "place": "places",
        "bot": "bots",
        "worker": "workers",
        "service": "services",
        "person": "people",
    }

    for section, fields in _REFERENCE_FIELDS.items():
        for item in registry[section]:
            slug = item["slug"]
            for field in fields:
                value = str(item.get(field) or "").strip()
                if not value:
                    continue
                target_section = section_targets[field]
                if value not in indexes[target_section]:
                    raise EstateRegistryError(
                        f"Section `{section}` entry `{slug}` references unknown "
                        f"{field} `{value}`"
                    )


def _validate_bbs_policy(registry: Dict[str, list[dict[str, Any]]]) -> None:
    for section in _BBS_POLICY_SECTIONS:
        for item in registry[section]:
            policy = item.get("bbs")
            if policy is None:
                continue
            slug = str(item.get("slug") or "").strip()
            if not isinstance(policy, dict):
                raise EstateRegistryError(
                    f"Section `{section}` entry `{slug}` bbs policy must be a mapping"
                )

            role = str(policy.get("role") or "").strip()
            if role not in _BBS_ROLES:
                raise EstateRegistryError(
                    f"Section `{section}` entry `{slug}` has unsupported bbs role `{role}`"
                )

            zone = str(policy.get("zone") or "").strip()
            if zone not in _BBS_ZONES:
                raise EstateRegistryError(
                    f"Section `{section}` entry `{slug}` has unsupported bbs zone `{zone}`"
                )

            channels = policy.get("channels", [])
            if not isinstance(channels, list) or not all(
                isinstance(channel, str) and channel.strip() for channel in channels
            ):
                raise EstateRegistryError(
                    f"Section `{section}` entry `{slug}` bbs channels must be a list of strings"
                )

            for field in _BBS_BOOL_FIELDS:
                if field in policy and not isinstance(policy[field], bool):
                    raise EstateRegistryError(
                        f"Section `{section}` entry `{slug}` bbs `{field}` must be boolean"
                    )


def _normalize_power_entries(
    raw: Any, *, section: str, slug: str
) -> dict[str, dict[str, Any]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise EstateRegistryError(
            f"Section `{section}` entry `{slug}` powers must be a mapping"
        )

    entries: dict[str, dict[str, Any]] = {}
    for raw_power, raw_value in raw.items():
        power = str(raw_power or "").strip().lower()
        if power not in POWER_CLASSES:
            raise EstateRegistryError(
                f"Section `{section}` entry `{slug}` has unsupported power `{power}`"
            )

        if isinstance(raw_value, str):
            entry: dict[str, Any] = {"level": raw_value.strip().lower()}
        elif isinstance(raw_value, dict):
            entry = dict(raw_value)
            entry["level"] = str(entry.get("level") or "").strip().lower()
        else:
            raise EstateRegistryError(
                f"Section `{section}` entry `{slug}` power `{power}` must be a string or mapping"
            )

        if entry["level"] not in POWER_LEVELS:
            raise EstateRegistryError(
                f"Section `{section}` entry `{slug}` power `{power}` has unsupported level `{entry['level']}`"
            )

        constraints = entry.get("constraints")
        if constraints is not None and (
            not isinstance(constraints, list)
            or not all(isinstance(item, str) and item.strip() for item in constraints)
        ):
            raise EstateRegistryError(
                f"Section `{section}` entry `{slug}` power `{power}` constraints must be a list of strings"
            )

        entries[power] = entry
    return entries


def _merge_power_entries(
    *entries: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged = {power: {"level": "none"} for power in POWER_CLASSES}
    for entry_map in entries:
        for power, entry in entry_map.items():
            merged[power] = dict(entry)
    return merged


def _power_active(entry: dict[str, Any] | None) -> bool:
    if not isinstance(entry, dict):
        return False
    return str(entry.get("level") or "none").strip().lower() not in _INERT_POWER_LEVELS


def _revocation_test_status(entry: dict[str, Any] | None) -> str:
    if not _power_active(entry):
        return "not_applicable"
    tested_at = str((entry or {}).get("revocation_tested_at") or "").strip().lower()
    if tested_at in _PENDING_REVOCATION_TEST_VALUES:
        return "pending"
    return "tested"


def _power_constraints(item: dict[str, Any]) -> dict[str, Any]:
    constraints = item.get("power_constraints")
    return constraints if isinstance(constraints, dict) else {}


def _has_extraordinary_constraint(item: dict[str, Any]) -> bool:
    constraints = _power_constraints(item)
    return bool(
        constraints.get("extraordinary_constraint")
        or item.get("extraordinary_constraint")
    )


def _validate_power_combination(
    *, section: str, slug: str, powers: dict[str, dict[str, Any]], item: dict[str, Any]
) -> None:
    if all(_power_active(powers.get(power)) for power in ("mouth", "purse", "seal")):
        if not _has_extraordinary_constraint(item):
            raise EstateRegistryError(
                f"Section `{section}` entry `{slug}` combines mouth, purse, and seal without extraordinary_constraint"
            )

    sword = powers.get("sword")
    if _power_active(sword):
        constraints = _power_constraints(item)
        responsible = str(
            (sword or {}).get("responsible_human")
            or constraints.get("responsible_human")
            or ""
        ).strip()
        purpose = str(
            (sword or {}).get("accountable_purpose")
            or constraints.get("accountable_purpose")
            or (sword or {}).get("emergency_purpose")
            or constraints.get("emergency_purpose")
            or ""
        ).strip()
        if not responsible or not purpose:
            raise EstateRegistryError(
                f"Section `{section}` entry `{slug}` has active sword power without responsible_human and accountable_purpose"
            )


def _power_issue(
    *,
    severity: str,
    section: str,
    slug: str,
    power: str,
    detail: str,
) -> dict[str, str]:
    return {
        "severity": severity,
        "section": section,
        "slug": slug,
        "power": power,
        "detail": detail,
    }


def _power_manifest_issues(
    *,
    section: str,
    item: dict[str, Any],
    profile: dict[str, Any],
    powers: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    slug = str(item.get("slug") or "").strip()
    issues: list[dict[str, str]] = []

    if _power_active(powers.get("mouth")) and not bool(
        profile.get("allows_outbound_send", False)
    ):
        issues.append(
            _power_issue(
                severity="warn",
                section=section,
                slug=slug,
                power="mouth",
                detail="mouth is active but the policy profile does not allow outbound send",
            )
        )

    constraints = _power_constraints(item)
    mouth = powers.get("mouth") or {}
    if _power_active(mouth):
        revoker = str(mouth.get("revoker") or constraints.get("revoker") or "")
        if not revoker:
            issues.append(
                _power_issue(
                    severity="warn",
                    section=section,
                    slug=slug,
                    power="mouth",
                    detail="mouth is active without revoker",
                )
            )

    if _power_active(powers.get("seal")) and not bool(
        profile.get("requires_approval", False)
    ):
        issues.append(
            _power_issue(
                severity="warn",
                section=section,
                slug=slug,
                power="seal",
                detail="seal is active without a requires_approval policy profile",
            )
        )

    purse = powers.get("purse") or {}
    if _power_active(purse):
        spend_cap = str(purse.get("spend_cap") or constraints.get("spend_cap") or "")
        revoker = str(purse.get("revoker") or constraints.get("revoker") or "")
        if not spend_cap or not revoker:
            issues.append(
                _power_issue(
                    severity="fail",
                    section=section,
                    slug=slug,
                    power="purse",
                    detail="purse is active without spend_cap and revoker",
                )
            )

    key = powers.get("key") or {}
    if _power_active(key):
        lease_source = str(
            key.get("lease_source") or constraints.get("lease_source") or ""
        )
        revoker = str(key.get("revoker") or constraints.get("revoker") or "")
        if not lease_source or not revoker:
            issues.append(
                _power_issue(
                    severity="warn",
                    section=section,
                    slug=slug,
                    power="key",
                    detail="key is active without lease_source and revoker",
                )
            )

    sword = powers.get("sword") or {}
    if _power_active(sword):
        responsible = str(
            sword.get("responsible_human") or constraints.get("responsible_human") or ""
        )
        purpose = str(
            sword.get("accountable_purpose")
            or constraints.get("accountable_purpose")
            or sword.get("emergency_purpose")
            or constraints.get("emergency_purpose")
            or ""
        )
        if not responsible or not purpose:
            issues.append(
                _power_issue(
                    severity="fail",
                    section=section,
                    slug=slug,
                    power="sword",
                    detail="sword is active without responsible_human and accountable_purpose",
                )
            )

    return issues


def _validate_power_policy(registry: Dict[str, list[dict[str, Any]]]) -> None:
    profile_powers: dict[str, dict[str, dict[str, Any]]] = {}
    for item in registry["policy_profiles"]:
        slug = str(item.get("slug") or "").strip()
        powers = _merge_power_entries(
            _normalize_power_entries(
                item.get("powers"), section="policy_profiles", slug=slug
            )
        )
        profile_powers[slug] = powers
        _validate_power_combination(
            section="policy_profiles", slug=slug, powers=powers, item=item
        )

    for section in ("bots", "workers", "assets", "services", "channels"):
        for item in registry[section]:
            slug = str(item.get("slug") or "").strip()
            profile_slug = str(item.get("policy_profile") or "").strip()
            powers = _merge_power_entries(
                profile_powers.get(profile_slug, {}),
                _normalize_power_entries(
                    item.get("powers"), section=section, slug=slug
                ),
            )
            _validate_power_combination(
                section=section, slug=slug, powers=powers, item=item
            )


def bbs_connector_config(item: dict[str, Any]) -> dict[str, Any]:
    policy = item.get("bbs")
    if not isinstance(policy, dict):
        return {}
    config: dict[str, Any] = {}
    for field, connector_field in _BBS_CONNECTOR_FIELD_MAP.items():
        if field not in policy:
            continue
        config[connector_field] = policy[field]
    return config


def load_registry(
    path: str | pathlib.Path = DEFAULT_REGISTRY_PATH,
) -> Dict[str, list[dict[str, Any]]]:
    registry_path = pathlib.Path(path).expanduser()
    if not registry_path.exists():
        raise EstateRegistryError(f"Registry not found: {registry_path}")
    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # pragma: no cover - exercised via invalid yaml path
        raise EstateRegistryError(f"Failed to parse registry: {registry_path}") from exc
    if not isinstance(raw, dict):
        raise EstateRegistryError("Registry root must be a mapping")

    normalized = _default_registry()
    for section in _SECTION_NAMES:
        value = raw.get(section) or []
        if not isinstance(value, list):
            raise EstateRegistryError(f"Registry `{section}` must be a list")
        normalized[section] = value

    _validate_references(normalized)
    _validate_bbs_policy(normalized)
    _validate_power_policy(normalized)
    return normalized


def effective_powers(
    item: dict[str, Any], profile_index: dict[str, dict[str, Any]], *, section: str
) -> dict[str, dict[str, Any]]:
    slug = str(item.get("slug") or "").strip()
    profile_slug = str(item.get("policy_profile") or "").strip()
    profile = profile_index.get(profile_slug, {})
    return _merge_power_entries(
        _normalize_power_entries(
            profile.get("powers"), section="policy_profiles", slug=profile_slug
        ),
        _normalize_power_entries(item.get("powers"), section=section, slug=slug),
    )


def power_manifest(registry: Dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    profiles = {
        str(item.get("slug") or "").strip(): item
        for item in registry.get("policy_profiles", [])
        if isinstance(item, dict)
    }
    profile_rows = []
    for slug, item in profiles.items():
        profile_rows.append(
            {
                "slug": slug,
                "display_name": item.get("display_name"),
                "mode": item.get("mode"),
                "powers": _merge_power_entries(
                    _normalize_power_entries(
                        item.get("powers"), section="policy_profiles", slug=slug
                    )
                ),
            }
        )

    items = []
    issues: list[dict[str, str]] = []
    for section in ("bots", "workers", "assets", "services", "channels"):
        for item in registry.get(section, []):
            if not isinstance(item, dict):
                continue
            powers = effective_powers(item, profiles, section=section)
            profile = profiles.get(str(item.get("policy_profile") or "").strip(), {})
            item_issues = _power_manifest_issues(
                section=section,
                item=item,
                profile=profile,
                powers=powers,
            )
            issues.extend(item_issues)
            items.append(
                {
                    "section": section,
                    "slug": item.get("slug"),
                    "display_name": item.get("display_name"),
                    "principal": item.get("principal"),
                    "policy_profile": item.get("policy_profile"),
                    "is_active": bool(item.get("is_active", True)),
                    "powers": powers,
                    "issues": item_issues,
                }
            )

    active_counts = {power: 0 for power in POWER_CLASSES}
    revocation_counts = {
        power: {"pending": 0, "tested": 0, "not_applicable": 0}
        for power in POWER_CLASSES
    }
    for item in items:
        if not item["is_active"]:
            continue
        for power, entry in item["powers"].items():
            if _power_active(entry):
                active_counts[power] += 1
            status = _revocation_test_status(entry)
            revocation_counts[power][status] += 1

    return {
        "power_classes": list(POWER_CLASSES),
        "power_levels": sorted(POWER_LEVELS),
        "enforcement_gates": POWER_ENFORCEMENT_GATES,
        "profiles": profile_rows,
        "items": items,
        "issues": issues,
        "summary": {
            "items": len(items),
            "active_items": sum(1 for item in items if item["is_active"]),
            "active_power_counts": active_counts,
            "revocation_tests": revocation_counts,
            "fail": sum(1 for issue in issues if issue["severity"] == "fail"),
            "warn": sum(1 for issue in issues if issue["severity"] == "warn"),
        },
    }


def init_registry(
    path: str | pathlib.Path = DEFAULT_REGISTRY_PATH,
    *,
    overwrite: bool = False,
) -> pathlib.Path:
    registry_path = pathlib.Path(path).expanduser()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    if registry_path.exists() and not overwrite:
        raise EstateRegistryError(f"Registry already exists: {registry_path}")
    if DEFAULT_TEMPLATE_PATH.exists():
        shutil.copyfile(DEFAULT_TEMPLATE_PATH, registry_path)
    else:
        registry_path.write_text(
            yaml.safe_dump(_default_registry(), sort_keys=False),
            encoding="utf-8",
        )
    return registry_path


def registry_summary(registry: Dict[str, list[dict[str, Any]]]) -> Dict[str, int]:
    return {section: len(registry.get(section) or []) for section in _SECTION_NAMES}
