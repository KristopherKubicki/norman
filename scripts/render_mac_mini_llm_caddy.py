#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from caddy_internal_tls import render_internal_tls_snippet


INTERNAL_TLS_SNIPPET_NAME = "mac_mini_llm_tls"
DEFAULT_LOCAL_HOST = "llm.home.arpa"
DEFAULT_CANONICAL_HOST = "llm.knox.lollie.org"
DEFAULT_UPSTREAM = "127.0.0.1:18151"


def _indent_block(block: str, prefix: str = "    ") -> list[str]:
    return [f"{prefix}{line}" if line else "" for line in block.splitlines()]


def _render_proxy_site(
    *,
    host: str,
    tls_config: str,
    upstream: str,
) -> str:
    lines = [
        f"http://{host} {{",
        "    redir https://{host}{uri} 308",
        "}",
        "",
        f"{host} {{",
    ]
    lines.extend(_indent_block(tls_config))
    lines.append(f"    reverse_proxy {upstream}")
    lines.append("}")
    return "\n".join(lines)


def render_caddy(
    *,
    local_host: str = DEFAULT_LOCAL_HOST,
    canonical_host: str = DEFAULT_CANONICAL_HOST,
    upstream: str = DEFAULT_UPSTREAM,
) -> str:
    internal_tls = f"import {INTERNAL_TLS_SNIPPET_NAME}"
    blocks = [
        render_internal_tls_snippet(INTERNAL_TLS_SNIPPET_NAME),
        "",
        _render_proxy_site(
            host=local_host,
            tls_config=internal_tls,
            upstream=upstream,
        ),
        "",
        _render_proxy_site(
            host=canonical_host,
            tls_config=internal_tls,
            upstream=upstream,
        ),
    ]
    return "\n".join(blocks)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the Mac mini Ollama/Caddy front door config."
    )
    parser.add_argument(
        "--local-host",
        default=DEFAULT_LOCAL_HOST,
        help="Local shortcut host that proxies to Norllama.",
    )
    parser.add_argument(
        "--canonical-host",
        default=DEFAULT_CANONICAL_HOST,
        help="Canonical site-specific LLM host.",
    )
    parser.add_argument(
        "--upstream",
        default=DEFAULT_UPSTREAM,
        help="Local Norllama upstream, usually 127.0.0.1:18151.",
    )
    args = parser.parse_args()
    print(
        render_caddy(
            local_host=args.local_host,
            canonical_host=args.canonical_host,
            upstream=args.upstream,
        )
    )


if __name__ == "__main__":
    main()
