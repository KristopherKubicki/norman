from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_mac_mini_llm_caddy_renderer():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "render_mac_mini_llm_caddy.py"
    )
    spec = importlib.util.spec_from_file_location(
        "render_mac_mini_llm_caddy",
        script_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_mac_mini_llm_caddy_renders_local_and_canonical_proxies() -> None:
    module = _load_mac_mini_llm_caddy_renderer()

    rendered = module.render_caddy()

    assert (
        "(mac_mini_llm_tls) {\n"
        "    tls {\n"
        "        issuer internal {\n"
        "            lifetime 6d\n"
        "        }\n"
        "    }\n"
        "}"
    ) in rendered
    assert (
        "http://llm.home.arpa {\n" "    redir https://{host}{uri} 308\n" "}"
    ) in rendered
    assert (
        "llm.home.arpa {\n"
        "    import mac_mini_llm_tls\n"
        "    reverse_proxy 127.0.0.1:18151\n"
        "}"
    ) in rendered
    assert (
        "http://llm.knox.lollie.org {\n" "    redir https://{host}{uri} 308\n" "}"
    ) in rendered
    assert (
        "llm.knox.lollie.org {\n"
        "    import mac_mini_llm_tls\n"
        "    reverse_proxy 127.0.0.1:18151\n"
        "}"
    ) in rendered


def test_mac_mini_llm_caddy_allows_host_and_upstream_overrides() -> None:
    module = _load_mac_mini_llm_caddy_renderer()

    rendered = module.render_caddy(
        local_host="llm.beach.home.arpa",
        canonical_host="llm.beach.lollie.org",
        upstream="127.0.0.1:22434",
    )

    assert "llm.beach.home.arpa" in rendered
    assert "llm.beach.lollie.org" in rendered
    assert "reverse_proxy 127.0.0.1:22434" in rendered
