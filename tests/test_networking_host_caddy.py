from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_networking_host_caddy_renderer():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "render_networking_host_caddy.py"
    )
    spec = importlib.util.spec_from_file_location(
        "render_networking_host_caddy",
        script_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_networking_host_caddy_matches_live_routes() -> None:
    module = _load_networking_host_caddy_renderer()

    rendered = module.render_caddy()

    assert (
        "(networking_internal_tls) {\n"
        "    tls {\n"
        "        issuer internal {\n"
        "            lifetime 6d\n"
        "        }\n"
        "    }\n"
        "}"
    ) in rendered
    assert (
        "http://networking.home.arpa, http://netops.home.arpa {\n"
        "    redir https://{host}{uri} 308\n"
        "}"
    ) in rendered
    assert (
        "networking.home.arpa, netops.home.arpa {\n"
        "    import networking_internal_tls\n"
        "    reverse_proxy 127.0.0.1:8791\n"
        "}"
    ) in rendered
    assert (
        "http://networking-host.home.arpa {\n"
        "    redir https://networking-host.home.arpa{uri} 308\n"
        "}"
    ) in rendered
    assert (
        "networking-host.home.arpa {\n"
        "    import networking_internal_tls\n"
        "    root * /var/www/host-home\n"
        "    file_server\n"
        "}"
    ) in rendered
    assert (
        ":80 {\n" "    root * /var/www/host-home\n" "    file_server\n" "}"
    ) in rendered


def test_networking_host_caddy_allows_upstream_and_root_overrides() -> None:
    module = _load_networking_host_caddy_renderer()

    rendered = module.render_caddy(
        networking_upstream="127.0.0.1:9999",
        host_home_root="/srv/networking-home",
    )

    assert "reverse_proxy 127.0.0.1:9999" in rendered
    assert "root * /srv/networking-home" in rendered
