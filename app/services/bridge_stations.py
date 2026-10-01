"""Canonical Bridge station routing and conversation capability rules."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit


_DEFAULT_FRONTDOOR = "https://norman.home.arpa"

# The Bridge uses the names presented in its directory. A station may expose a
# different canonical console name behind the shared frontdoor.
STATION_SLUG_ALIASES = {
    "eyebat": "glimpser",
    "glimpse": "glimpser",
    "keystone": "compere",
    "netops": "networking",
    "pef": "parkergale",
    "pefb": "parkergale",
}

# These identities are estate/service surfaces, not prompt-capable station
# consoles. Keep them out of Bridge direct messages until they implement the
# common station history and prompt contract.
NON_CONVERSATIONAL_STATION_SLUGS = frozenset({"dohio", "maps"})


def bridge_station_slug(value: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return STATION_SLUG_ALIASES.get(slug, slug)


def supports_direct_conversation(value: Any) -> bool:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return bool(slug) and slug not in NON_CONVERSATIONAL_STATION_SLUGS


def bridge_station_url(value: Any) -> str:
    """Return the shared Caddy route for a station, never the app's own URL."""

    origin = str(
        os.getenv("NORMAN_BRIDGE_STATION_FRONTDOOR", _DEFAULT_FRONTDOOR)
    ).strip()
    parts = urlsplit(origin)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise RuntimeError("NORMAN_BRIDGE_STATION_FRONTDOOR must be an http(s) URL")
    slug = bridge_station_slug(value)
    if not slug:
        return ""
    path = f"{parts.path.rstrip('/')}/bot/{quote(slug, safe='')}/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
