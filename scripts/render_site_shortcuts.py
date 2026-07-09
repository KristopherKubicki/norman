#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from app.services import estate_registry
from app.services.site_shortcuts import build_site_shortcuts, site_place_index
from caddy_internal_tls import render_internal_tls_snippet


INTERNAL_TLS_SNIPPET_NAME = "site_local_tls"


def _render_redirect_site(local_host: str, canonical_host: str) -> str:
    return f"""
http://{local_host} {{
    redir https://{{host}}{{uri}} 308
}}

{local_host} {{
    import {INTERNAL_TLS_SNIPPET_NAME}
    redir https://{canonical_host}{{uri}} 308
}}
""".strip()


def render_inventory(
    registry: dict[str, list[dict[str, object]]],
    *,
    site_slug: str,
) -> str:
    site = site_place_index(registry)[site_slug]
    lines = [
        f"site={site.slug} display={site.display_name} site_root={site.site_root} "
        f"local_zone={site.local_zone} frontdoor_host={site.shortcut_frontdoor_host or '-'} "
        f"frontdoor_address={site.shortcut_frontdoor_address or '-'}"
    ]
    for shortcut in build_site_shortcuts(registry, site_slug):
        lines.append(
            f"{shortcut.local_host} -> https://{shortcut.canonical_host}/ [{shortcut.display_name}]"
        )
    return "\n".join(lines)


def render_dns_json(
    registry: dict[str, list[dict[str, object]]],
    *,
    site_slug: str,
    frontdoor_address: str = "",
) -> str:
    site = site_place_index(registry)[site_slug]
    address = frontdoor_address.strip() or site.shortcut_frontdoor_address
    if not address:
        raise estate_registry.EstateRegistryError(
            f"Site `{site_slug}` does not define shortcut_frontdoor_address"
        )
    dns_map = {
        shortcut.local_host: address
        for shortcut in build_site_shortcuts(registry, site_slug)
    }
    return json.dumps(dns_map, indent=2, sort_keys=True)


def render_caddy(
    registry: dict[str, list[dict[str, object]]],
    *,
    site_slug: str,
) -> str:
    blocks = [render_internal_tls_snippet(INTERNAL_TLS_SNIPPET_NAME)]
    for shortcut in build_site_shortcuts(registry, site_slug):
        blocks.extend(
            [
                "",
                _render_redirect_site(shortcut.local_host, shortcut.canonical_host),
            ]
        )
    return "\n".join(blocks)


def render_probe_json(
    registry: dict[str, list[dict[str, object]]],
    *,
    site_slug: str,
) -> str:
    payload = [
        {
            "label": shortcut.display_name,
            "local_host": shortcut.local_host,
            "canonical_host": shortcut.canonical_host,
            "site": shortcut.site_slug,
        }
        for shortcut in build_site_shortcuts(registry, site_slug)
    ]
    return json.dumps(payload, indent=2, sort_keys=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render site-local home.arpa shortcut plans from the estate registry."
    )
    parser.add_argument(
        "--site", required=True, help="Site place slug, for example `knox`."
    )
    parser.add_argument(
        "--registry",
        default="",
        help="Optional estate registry path. Defaults to runtime registry/template resolution.",
    )
    parser.add_argument(
        "--mode",
        choices=("inventory", "dns-json", "caddy", "probe-json"),
        default="inventory",
        help="Which artifact to render.",
    )
    parser.add_argument(
        "--frontdoor-address",
        default="",
        help="Override the site shortcut frontdoor IP/address for dns-json rendering.",
    )
    return parser.parse_args(argv)


def load_runtime_registry(path: str = "") -> dict[str, list[dict[str, object]]]:
    if path:
        return estate_registry.load_registry(path)
    runtime_path = estate_registry.DEFAULT_REGISTRY_PATH
    if Path(runtime_path).expanduser().exists():
        return estate_registry.load_registry(runtime_path)
    return estate_registry.load_registry(estate_registry.DEFAULT_TEMPLATE_PATH)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    registry = load_runtime_registry(args.registry)
    if args.mode == "inventory":
        print(render_inventory(registry, site_slug=args.site))
    elif args.mode == "dns-json":
        print(
            render_dns_json(
                registry,
                site_slug=args.site,
                frontdoor_address=args.frontdoor_address,
            )
        )
    elif args.mode == "caddy":
        print(render_caddy(registry, site_slug=args.site))
    else:
        print(render_probe_json(registry, site_slug=args.site))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
