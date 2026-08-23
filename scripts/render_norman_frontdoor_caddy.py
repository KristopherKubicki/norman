#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from sync_agent_console_template import HOSTS, host_canonical_host, host_frontdoor_hosts

INTERNAL_TLS_SNIPPET_NAME = "norman_internal_tls"
LOLLIE_ACME_DIRECTORY = "https://ca.home.arpa/acme/acme/directory"
TAILNET_CERT_PATH = "/etc/caddy/certs/norman.tail94915.ts.net.crt"
TAILNET_KEY_PATH = "/etc/caddy/certs/norman.tail94915.ts.net.key"


def _indent_block(block: str, prefix: str = "    ") -> list[str]:
    return [f"{prefix}{line}" if line else "" for line in block.splitlines()]


def render_internal_tls_snippet() -> str:
    return f"""
({INTERNAL_TLS_SNIPPET_NAME}) {{
    tls {{
        ca {LOLLIE_ACME_DIRECTORY}
    }}
}}
""".strip()


def render_global_options() -> str:
    return f"""
{{
    acme_ca {LOLLIE_ACME_DIRECTORY}
}}
""".strip()


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

    @bridge_document path /bridge /bridge.html
    header @bridge_document Cache-Control "no-store, max-age=0"

    @bridge_live_assets path /static/css/bridge.css /static/js/bridge.js
    handle @bridge_live_assets {
        reverse_proxy 127.0.0.1:8000 {
            header_down Cache-Control "no-store, max-age=0"
        }
    }

    handle_path /static/* {
        root * /var/www/norman-static
        header Cache-Control "public, max-age=300, stale-while-revalidate=86400"
        file_server
    }

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

    handle /v1/* {
        reverse_proxy 127.0.0.1:8000 {
            header_up X-Norman-Gateway-Route norman
            header_up X-Forwarded-For 127.0.0.2
        }
    }

    @norman_root path /
    handle @norman_root {
        redir * /bridge 302
    }

    handle {
        reverse_proxy 127.0.0.1:8000
    }
}
""".strip()


def render_caddy() -> str:
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

    blocks = [
        render_global_options(),
        "",
        render_internal_tls_snippet(),
        "",
        *blocks,
        "",
        _render_site_block(
            (canonical_host,),
            tls_config=f"tls {TAILNET_CERT_PATH} {TAILNET_KEY_PATH}",
        ),
        "",
        "import /etc/caddy/includes/norman-bot-hosts.caddy",
    ]
    return "\n".join(blocks)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the Norman front-door Caddy config."
    )
    parser.parse_args()
    print(render_caddy())


if __name__ == "__main__":
    main()
