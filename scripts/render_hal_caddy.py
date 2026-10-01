#!/usr/bin/env python3
"""Render Hal's Caddy configuration with automatic Lollie ACME certificates."""

from __future__ import annotations

import argparse


LOLLIE_ACME_DIRECTORY = "https://ca.home.arpa/acme/acme/directory"
INTERNAL_TLS_SNIPPET_NAME = "hal_internal_tls"
HAL_HOST = "hal.home.arpa"
HOST_HOME_ROOT = "/var/www/host-home"
HUBITAT_UPSTREAM = "127.0.0.1:8096"


def render_caddy(
    *,
    host_home_root: str = HOST_HOME_ROOT,
    hubitat_upstream: str = HUBITAT_UPSTREAM,
) -> str:
    """Render the active Hal routes with an automatically managed certificate."""
    return f"""
{{
    acme_ca {LOLLIE_ACME_DIRECTORY}
}}

({INTERNAL_TLS_SNIPPET_NAME}) {{
    tls {{
        ca {LOLLIE_ACME_DIRECTORY}
    }}
}}

http://camera.localhost {{
    redir https://camera.localhost{{uri}} 308
}}

camera.localhost {{
    tls internal
    reverse_proxy 127.0.0.1:9007
}}

http://{HAL_HOST} {{
    redir https://{HAL_HOST}{{uri}} 308
}}

{HAL_HOST} {{
    import {INTERNAL_TLS_SNIPPET_NAME}

    redir /hubitat /hubitat/ 308
    handle_path /hubitat/* {{
        reverse_proxy {hubitat_upstream}
    }}

    handle {{
        root * {host_home_root}
        file_server
    }}
}}

:80 {{
    root * {host_home_root}
    file_server
}}
""".strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render Hal's automatic-TLS Caddy configuration."
    )
    parser.add_argument("--host-home-root", default=HOST_HOME_ROOT)
    parser.add_argument("--hubitat-upstream", default=HUBITAT_UPSTREAM)
    args = parser.parse_args()
    print(
        render_caddy(
            host_home_root=args.host_home_root,
            hubitat_upstream=args.hubitat_upstream,
        )
    )


if __name__ == "__main__":
    main()
