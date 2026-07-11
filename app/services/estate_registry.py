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
    "site_shortcuts",
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
    "site_shortcuts": (),
    "bots": ("principal", "domain", "policy_profile"),
    "workers": ("principal", "place", "control_class", "policy_profile"),
    "assets": ("principal", "place", "worker", "control_class"),
    "services": ("principal", "domain", "bot", "worker", "place", "policy_profile"),
    "channels": ("principal", "domain", "bot", "service", "policy_profile", "person"),
    "people": ("principal",),
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


def _site_places(
    registry: Dict[str, list[dict[str, Any]]],
) -> Dict[str, dict[str, Any]]:
    site_places: Dict[str, dict[str, Any]] = {}
    seen_roots: Dict[str, str] = {}
    for item in registry["places"]:
        slug = item["slug"]
        site_root = str(item.get("site_root") or "").strip().lower()
        if not site_root:
            continue
        if site_root in seen_roots:
            raise EstateRegistryError(
                f"Places `{slug}` and `{seen_roots[site_root]}` share site_root `{site_root}`"
            )
        seen_roots[site_root] = slug
        site_places[slug] = item
    return site_places


def _validate_site_shortcuts(registry: Dict[str, list[dict[str, Any]]]) -> None:
    site_places = _site_places(registry)
    site_place_slugs = set(site_places)
    local_hosts: Dict[str, str] = {}
    for item in registry["site_shortcuts"]:
        slug = item["slug"]
        display_name = str(item.get("display_name") or "").strip()
        local_host = str(item.get("local_host") or "").strip().lower()
        canonical_label = str(item.get("canonical_label") or slug).strip().lower()
        if not display_name:
            raise EstateRegistryError(
                f"Section `site_shortcuts` entry `{slug}` must include `display_name`"
            )
        if not local_host:
            raise EstateRegistryError(
                f"Section `site_shortcuts` entry `{slug}` must include `local_host`"
            )
        if not local_host.endswith(".home.arpa"):
            raise EstateRegistryError(
                f"Section `site_shortcuts` entry `{slug}` local_host must end with `.home.arpa`"
            )
        if local_host in local_hosts:
            raise EstateRegistryError(
                f"Section `site_shortcuts` entries `{slug}` and "
                f"`{local_hosts[local_host]}` share local_host `{local_host}`"
            )
        local_hosts[local_host] = slug
        if not canonical_label:
            raise EstateRegistryError(
                f"Section `site_shortcuts` entry `{slug}` must include a canonical label"
            )
        places = item.get("places") or []
        if places and not isinstance(places, list):
            raise EstateRegistryError(
                f"Section `site_shortcuts` entry `{slug}` places must be a list"
            )
        for place_slug in places:
            clean = str(place_slug or "").strip()
            if clean not in site_place_slugs:
                raise EstateRegistryError(
                    f"Section `site_shortcuts` entry `{slug}` references unknown site place `{clean}`"
                )


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
    _validate_site_shortcuts(normalized)
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
