from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

from app.services import estate_registry, site_shortcuts


VALID_REGISTRY = """
principals:
  - slug: alpha
    display_name: Alpha
    kind: person
policy_profiles: []
control_classes: []
domains: []
places:
  - slug: knox
    principal: alpha
    display_name: Knox
    kind: home
    site_root: knox.lollie.org
    local_zone: home.arpa
    shortcut_frontdoor_host: norman.home.arpa
    shortcut_frontdoor_address: 192.168.2.241
  - slug: beach
    principal: alpha
    display_name: Beach
    kind: property
    site_root: beach.lollie.org
    local_zone: home.arpa
site_shortcuts:
  - slug: hubitat
    display_name: Hubitat
    local_host: hubitat.home.arpa
    canonical_label: hubitat
    places:
      - knox
      - beach
  - slug: printer
    display_name: Printer
    local_host: printer.home.arpa
    canonical_label: printer
    places:
      - knox
  - slug: llm
    display_name: Local LLM
    local_host: llm.home.arpa
    canonical_label: llm
    places:
      - knox
bots: []
workers: []
assets: []
services: []
channels: []
people: []
"""


def _load_registry(tmp_path: pathlib.Path):
    path = tmp_path / "registry.yaml"
    path.write_text(VALID_REGISTRY, encoding="utf-8")
    return estate_registry.load_registry(path)


def _load_site_shortcuts_renderer():
    script_path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "scripts"
        / "render_site_shortcuts.py"
    )
    spec = importlib.util.spec_from_file_location("render_site_shortcuts", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_site_shortcuts_maps_local_hosts_to_site_root(
    tmp_path: pathlib.Path,
) -> None:
    registry = _load_registry(tmp_path)

    items = site_shortcuts.build_site_shortcuts(registry, "knox")

    assert [item.local_host for item in items] == [
        "hubitat.home.arpa",
        "printer.home.arpa",
        "llm.home.arpa",
    ]
    assert [item.canonical_host for item in items] == [
        "hubitat.knox.lollie.org",
        "printer.knox.lollie.org",
        "llm.knox.lollie.org",
    ]


def test_render_site_shortcuts_caddy_uses_site_specific_redirects(
    tmp_path: pathlib.Path,
) -> None:
    module = _load_site_shortcuts_renderer()
    registry = _load_registry(tmp_path)

    rendered = module.render_caddy(registry, site_slug="beach")

    assert (
        "(site_local_tls) {\n"
        "    tls {\n"
        "        issuer internal {\n"
        "            lifetime 6d\n"
        "        }\n"
        "    }\n"
        "}"
    ) in rendered
    assert (
        "hubitat.home.arpa {\n    import site_local_tls\n    redir https://hubitat.beach.lollie.org{uri} 308\n}"
        in rendered
    )
    assert "printer.home.arpa" not in rendered
    assert "llm.home.arpa" not in rendered


def test_render_site_shortcuts_dns_json_uses_site_frontdoor_address(
    tmp_path: pathlib.Path,
) -> None:
    module = _load_site_shortcuts_renderer()
    registry = _load_registry(tmp_path)

    rendered = module.render_dns_json(registry, site_slug="knox")

    assert json.loads(rendered) == {
        "hubitat.home.arpa": "192.168.2.241",
        "printer.home.arpa": "192.168.2.241",
        "llm.home.arpa": "192.168.2.241",
    }
