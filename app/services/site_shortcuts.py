from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services import estate_registry


DEFAULT_LOCAL_ZONE = "home.arpa"


@dataclass(frozen=True)
class SitePlace:
    slug: str
    display_name: str
    site_root: str
    local_zone: str
    shortcut_frontdoor_host: str
    shortcut_frontdoor_address: str
    notes: str


@dataclass(frozen=True)
class SiteShortcut:
    slug: str
    display_name: str
    site_slug: str
    site_root: str
    local_host: str
    canonical_host: str
    shortcut_frontdoor_host: str
    shortcut_frontdoor_address: str
    notes: str


def iter_site_places(
    registry: dict[str, list[dict[str, Any]]],
) -> list[SitePlace]:
    places: list[SitePlace] = []
    for item in registry.get("places") or []:
        site_root = str(item.get("site_root") or "").strip().lower()
        if not site_root:
            continue
        places.append(
            SitePlace(
                slug=item["slug"],
                display_name=str(item.get("display_name") or item["slug"]).strip(),
                site_root=site_root,
                local_zone=str(item.get("local_zone") or DEFAULT_LOCAL_ZONE)
                .strip()
                .lower(),
                shortcut_frontdoor_host=str(
                    item.get("shortcut_frontdoor_host") or ""
                ).strip(),
                shortcut_frontdoor_address=str(
                    item.get("shortcut_frontdoor_address") or ""
                ).strip(),
                notes=str(item.get("notes") or "").strip(),
            )
        )
    return places


def site_place_index(
    registry: dict[str, list[dict[str, Any]]],
) -> dict[str, SitePlace]:
    return {place.slug: place for place in iter_site_places(registry)}


def build_site_shortcuts(
    registry: dict[str, list[dict[str, Any]]],
    site_slug: str,
) -> list[SiteShortcut]:
    places = site_place_index(registry)
    site = places.get(str(site_slug or "").strip())
    if site is None:
        raise estate_registry.EstateRegistryError(f"Unknown site place: {site_slug}")

    shortcuts: list[SiteShortcut] = []
    for item in registry.get("site_shortcuts") or []:
        allowed_places = [
            str(value or "").strip() for value in item.get("places") or []
        ]
        if allowed_places and site.slug not in allowed_places:
            continue
        canonical_label = (
            str(item.get("canonical_label") or item["slug"]).strip().lower()
        )
        local_host = str(item.get("local_host") or "").strip().lower()
        shortcuts.append(
            SiteShortcut(
                slug=item["slug"],
                display_name=str(item.get("display_name") or item["slug"]).strip(),
                site_slug=site.slug,
                site_root=site.site_root,
                local_host=local_host,
                canonical_host=f"{canonical_label}.{site.site_root}",
                shortcut_frontdoor_host=site.shortcut_frontdoor_host,
                shortcut_frontdoor_address=site.shortcut_frontdoor_address,
                notes=str(item.get("notes") or "").strip(),
            )
        )
    return shortcuts
