#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from caddy_internal_tls import (
    INTERNAL_LEAF_LIFETIME as SHARED_INTERNAL_LEAF_LIFETIME,
)
from caddy_internal_tls import (
    render_internal_tls_snippet as _render_internal_tls_snippet,
)
from sync_agent_console_template import HOSTS, host_canonical_host, host_frontdoor_hosts

INTERNAL_TLS_SNIPPET_NAME = "norman_internal_tls"
INTERNAL_LEAF_LIFETIME = SHARED_INTERNAL_LEAF_LIFETIME


def _indent_block(block: str, prefix: str = "    ") -> list[str]:
    return [f"{prefix}{line}" if line else "" for line in block.splitlines()]


def render_internal_tls_snippet() -> str:
    return _render_internal_tls_snippet(INTERNAL_TLS_SNIPPET_NAME)


def _comma_join(hosts: tuple[str, ...]) -> str:
    return ", ".join(hosts)


def _http_hosts(hosts: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"http://{host}" for host in hosts)


def _render_site_block(
    hosts: tuple[str, ...],
    *,
    tls_config: str,
    import_frontdoor: bool = True,
) -> str:
    lines = [
        f"{_comma_join(_http_hosts(hosts))} {{",
        "    redir https://{host}{uri} 308",
        "}",
        "",
        f"{_comma_join(hosts)} {{",
    ]
    lines.extend(_indent_block(tls_config))
    if import_frontdoor:
        lines.append("    import norman_frontdoor")
    lines.append("}")
    return "\n".join(lines)


def render_frontdoor_snippet() -> str:
    return """
(norman_frontdoor) {
    encode gzip zstd

    redir /host /host/ 308
    handle_path /host/* {
        root * /var/www/host-home
        file_server
    }

    redir /codex /codex/ 308
    handle_path /codex/* {
        reverse_proxy 127.0.0.1:8788
    }

    redir /bot /bot/ 308
    import /etc/caddy/includes/norman-bots.caddy

    handle {
        reverse_proxy 127.0.0.1:8000
    }
}
""".strip()


def render_caddy(
    *,
    canonical_cert: str = "",
    canonical_key: str = "",
) -> str:
    norman = HOSTS["norman"]
    canonical_host = host_canonical_host(norman)
    shortcut_hosts = tuple(
        host for host in host_frontdoor_hosts(norman) if host != canonical_host
    )
    blocks: list[str] = [render_frontdoor_snippet()]
    internal_tls = f"import {INTERNAL_TLS_SNIPPET_NAME}"

    if shortcut_hosts:
        blocks.extend(
            [
                "",
                _render_site_block(
                    shortcut_hosts,
                    tls_config=internal_tls,
                ),
            ]
        )

    canonical_tls = (
        f"tls {canonical_cert} {canonical_key}"
        if canonical_cert and canonical_key
        else internal_tls
    )
    blocks = [
        render_internal_tls_snippet(),
        "",
        *blocks,
        "",
        _render_site_block((canonical_host,), tls_config=canonical_tls),
        "",
        "import /etc/caddy/includes/norman-bot-hosts.caddy",
    ]
    return "\n".join(blocks)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the Norman front-door Caddy config."
    )
    parser.add_argument(
        "--canonical-cert",
        default="",
        help="Optional certificate file path for Norman's canonical host.",
    )
    parser.add_argument(
        "--canonical-key",
        default="",
        help="Optional private key path for Norman's canonical host.",
    )
    args = parser.parse_args()
    print(
        render_caddy(
            canonical_cert=args.canonical_cert,
            canonical_key=args.canonical_key,
        )
    )


if __name__ == "__main__":
    main()
