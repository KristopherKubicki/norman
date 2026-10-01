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
        "(networking_lollie_tls) {\n"
        "\ttls /etc/caddy/certs/networking-lollie.crt "
        "/etc/caddy/certs/networking-lollie.key\n"
        "}"
    ) in rendered
    assert (
        "(private_clients) {\n"
        "\t@private_clients remote_ip 127.0.0.1/8 ::1 192.168.2.0/24"
    ) in rendered
    assert (
        "http://networking.home.arpa, http://networking.home.lollie.org, "
        "http://networking.knox.lollie.org, http://networking-host.home.arpa {\n"
        "\timport private_clients"
    ) in rendered
    assert (
        "networking.home.arpa, networking.home.lollie.org, "
        "networking.knox.lollie.org, networking-host.home.arpa {\n"
        "\timport networking_lollie_tls\n"
        "\timport private_clients\n"
        "\thandle @private_clients {\n"
        "\t\thandle /v1/* {\n"
        "\t\t\treverse_proxy https://192.168.2.241 {\n"
        "\t\t\t\theader_up Host netbot.home.arpa\n"
        "\t\t\t\ttransport http {\n"
        "\t\t\t\t\ttls_server_name netbot.home.arpa"
    ) in rendered
    assert rendered.index("handle /v1/* {") < rendered.index(
        "\t\thandle {\n\t\t\troot * /var/www/host-home"
    )
    assert (
        "netops.home.arpa {\n"
        "\timport networking_lollie_tls\n"
        "\timport private_clients\n"
        "\thandle @private_clients {\n"
        "\t\treverse_proxy 127.0.0.1:8791"
    ) in rendered
    assert (
        ":80 {\n"
        "\timport private_clients\n"
        "\thandle @private_clients {\n"
        "\t\troot * /var/www/host-home\n"
        "\t\tfile_server"
    ) in rendered


def test_networking_host_caddy_allows_upstream_and_root_overrides() -> None:
    module = _load_networking_host_caddy_renderer()

    rendered = module.render_caddy(
        networking_upstream="127.0.0.1:9999",
        host_home_root="/srv/networking-home",
        gateway_upstream="https://192.168.2.250",
    )

    assert "reverse_proxy 127.0.0.1:9999" in rendered
    assert "reverse_proxy https://192.168.2.250" in rendered
    assert "root * /srv/networking-home" in rendered
