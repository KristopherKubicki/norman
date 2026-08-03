from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_hal_caddy_renderer():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "render_hal_caddy.py"
    )
    spec = importlib.util.spec_from_file_location("render_hal_caddy", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_hal_caddy_uses_automatic_lollie_acme_and_keeps_active_routes() -> None:
    module = _load_hal_caddy_renderer()

    rendered = module.render_caddy()

    assert (
        "{\n" "    acme_ca https://ca.home.arpa/acme/acme/directory\n" "}"
    ) in rendered
    assert (
        "(hal_internal_tls) {\n"
        "    tls {\n"
        "        ca https://ca.home.arpa/acme/acme/directory\n"
        "    }\n"
        "}"
    ) in rendered
    assert "tls /etc/caddy/certs/hal-lollie.crt" not in rendered
    assert (
        "hal.home.arpa {\n"
        "    import hal_internal_tls\n"
        "\n"
        "    redir /hubitat /hubitat/ 308\n"
        "    handle_path /hubitat/* {\n"
        "        reverse_proxy 127.0.0.1:8096\n"
        "    }"
    ) in rendered
    assert (
        "camera.localhost {\n"
        "    tls internal\n"
        "    reverse_proxy 127.0.0.1:9007\n"
        "}"
    ) in rendered


def test_hal_caddy_allows_route_overrides() -> None:
    module = _load_hal_caddy_renderer()

    rendered = module.render_caddy(
        host_home_root="/srv/hal-home",
        hubitat_upstream="127.0.0.1:9999",
    )

    assert "root * /srv/hal-home" in rendered
    assert "reverse_proxy 127.0.0.1:9999" in rendered
