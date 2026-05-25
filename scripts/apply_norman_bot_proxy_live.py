#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from render_norman_bot_proxy_caddy import render_dns_json, render_hosts, render_paths


DEFAULT_CADDYFILE = Path("/etc/caddy/Caddyfile")
DEFAULT_ADMIN_LOAD_URL = "http://127.0.0.1:2019/load"
DEFAULT_ADMIN_CONFIG_URL = "http://127.0.0.1:2019/config/"


def adapt_caddyfile(caddyfile: Path, paths_include: Path, hosts_include: Path) -> str:
    source = caddyfile.read_text(encoding="utf-8")
    rendered = source.replace(
        "/etc/caddy/includes/norman-bots.caddy", str(paths_include)
    ).replace("/etc/caddy/includes/norman-bot-hosts.caddy", str(hosts_include))

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(rendered)
        temp_caddyfile = Path(handle.name)

    try:
        result = subprocess.run(
            [
                "caddy",
                "adapt",
                "--config",
                str(temp_caddyfile),
                "--adapter",
                "caddyfile",
                "--pretty",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout
    finally:
        temp_caddyfile.unlink(missing_ok=True)


def post_json(url: str, payload: str) -> str:
    request = urllib.request.Request(
        url,
        data=payload.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Caddy admin load failed: HTTP {exc.code}: {body}") from exc


def get_admin_config(url: str) -> str:
    with urllib.request.urlopen(url, timeout=8) as response:
        return response.read().decode("utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Render Norman bot proxy includes and load them into the live Caddy "
            "admin API. This does not write /etc/caddy/includes."
        )
    )
    parser.add_argument("--caddyfile", type=Path, default=DEFAULT_CADDYFILE)
    parser.add_argument("--admin-load-url", default=DEFAULT_ADMIN_LOAD_URL)
    parser.add_argument("--admin-config-url", default=DEFAULT_ADMIN_CONFIG_URL)
    parser.add_argument("--dns-output", type=Path)
    parser.add_argument("--dns-target", choices=("lan", "tailnet"), default="tailnet")
    parser.add_argument(
        "--require-host",
        action="append",
        default=[],
        help="Host that must appear in the live Caddy config after load.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render and adapt the config, but do not load it into Caddy.",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        paths_include = temp_root / "norman-bots.caddy"
        hosts_include = temp_root / "norman-bot-hosts.caddy"
        paths_include.write_text(render_paths(), encoding="utf-8")
        hosts_include.write_text(render_hosts(), encoding="utf-8")
        adapted_json = adapt_caddyfile(args.caddyfile, paths_include, hosts_include)

        parsed = json.loads(adapted_json)
        route_count = len(
            parsed.get("apps", {})
            .get("http", {})
            .get("servers", {})
            .get("srv0", {})
            .get("routes", [])
        )
        print(f"adapted routes={route_count}")

        if args.dns_output:
            args.dns_output.parent.mkdir(parents=True, exist_ok=True)
            args.dns_output.write_text(
                render_dns_json(args.dns_target) + "\n", encoding="utf-8"
            )
            print(f"dns -> {args.dns_output}")

        if args.dry_run:
            return 0

        post_json(args.admin_load_url, adapted_json)
        print("live caddy load=ok")

    live_config = get_admin_config(args.admin_config_url)
    for host in args.require_host:
        if host not in live_config:
            raise RuntimeError(f"required host missing from live Caddy config: {host}")
        print(f"verified host={host}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
