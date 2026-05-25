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
_BBS_ROLES = {"broker", "root", "operator", "work", "personal", "network", "private"}
_BBS_ZONES = {"root", "global", "work", "personal", "network", "private"}
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
    return normalized


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
