#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from caddy_internal_tls import render_internal_tls_snippet
from sync_agent_console_template import HOSTS


INTERNAL_TLS_SNIPPET_NAME = "networking_internal_tls"
NETWORKING_CONSOLE_HOSTS = ("networking.home.arpa", "netops.home.arpa")
NETWORKING_CONSOLE_UPSTREAM = "127.0.0.1:8791"
DEFAULT_HOST_HOME_ROOT = "/var/www/host-home"


def _indent_block(block: str, prefix: str = "    ") -> list[str]:
    return [f"{prefix}{line}" if line else "" for line in block.splitlines()]


def _comma_join(hosts: tuple[str, ...]) -> str:
    return ", ".join(hosts)


def _http_hosts(hosts: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"http://{host}" for host in hosts)


def _render_reverse_proxy_site(
    hosts: tuple[str, ...],
    *,
    tls_config: str,
    upstream: str,
) -> str:
    lines = [
        f"{_comma_join(_http_hosts(hosts))} {{",
        "    redir https://{host}{uri} 308",
        "}",
        "",
        f"{_comma_join(hosts)} {{",
    ]
    lines.extend(_indent_block(tls_config))
    lines.append(f"    reverse_proxy {upstream}")
    lines.append("}")
    return "\n".join(lines)


def _render_file_server_site(
    hosts: tuple[str, ...],
    *,
    tls_config: str,
    root: str,
) -> str:
    canonical_host = hosts[0]
    lines = [
        f"http://{canonical_host} {{",
        f"    redir https://{canonical_host}" + "{uri} 308",
        "}",
        "",
        f"{_comma_join(hosts)} {{",
    ]
    lines.extend(_indent_block(tls_config))
    lines.extend(
        [
            f"    root * {root}",
            "    file_server",
            "}",
        ]
    )
    return "\n".join(lines)


def _render_default_http_site(root: str) -> str:
    return f"""
:80 {{
    root * {root}
    file_server
}}
""".strip()


def render_caddy(
    *,
    networking_upstream: str = NETWORKING_CONSOLE_UPSTREAM,
    host_home_root: str = "",
) -> str:
    networking_host = HOSTS["networking-host"]
    resolved_host_home_root = host_home_root.strip()
    if not resolved_host_home_root:
        if networking_host.host_home_path:
            resolved_host_home_root = str(Path(networking_host.host_home_path).parent)
        else:
            resolved_host_home_root = DEFAULT_HOST_HOME_ROOT
    internal_tls = f"import {INTERNAL_TLS_SNIPPET_NAME}"
    blocks = [
        render_internal_tls_snippet(INTERNAL_TLS_SNIPPET_NAME),
        "",
        _render_reverse_proxy_site(
            NETWORKING_CONSOLE_HOSTS,
            tls_config=internal_tls,
            upstream=networking_upstream,
        ),
        "",
        _render_file_server_site(
            (networking_host.public_host,),
            tls_config=internal_tls,
            root=resolved_host_home_root,
        ),
        "",
        _render_default_http_site(resolved_host_home_root),
    ]
    return "\n".join(blocks)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the networking-host Caddy config."
    )
    parser.add_argument(
        "--networking-upstream",
        default=NETWORKING_CONSOLE_UPSTREAM,
        help="Local upstream for the networking console surface.",
    )
    parser.add_argument(
        "--host-home-root",
        default="",
        help="Override the host-home document root path.",
    )
    args = parser.parse_args()
    print(
        render_caddy(
            networking_upstream=args.networking_upstream,
            host_home_root=args.host_home_root,
        )
    )


if __name__ == "__main__":
    main()
