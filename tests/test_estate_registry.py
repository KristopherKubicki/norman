from __future__ import annotations

import pathlib

import pytest

from app.services import estate_registry


VALID_REGISTRY = """
principals:
  - slug: alpha
    display_name: Alpha
    kind: person
policy_profiles:
  - slug: manual
    display_name: Manual
    mode: manual
control_classes:
  - slug: root-controlled
    display_name: Root Controlled
    rank: 100
domains:
  - slug: alpha-ops
    principal: alpha
    display_name: Ops
    kind: ops
    default_policy_profile: manual
places:
  - slug: home
    principal: alpha
    display_name: Home
    kind: home
    site_root: alpha.lollie.org
    local_zone: home.arpa
    shortcut_frontdoor_address: 192.168.2.10
site_shortcuts:
  - slug: hubitat
    display_name: Hubitat
    local_host: hubitat.home.arpa
    canonical_label: hubitat
    places:
      - home
bots:
  - slug: alpha-bot
    principal: alpha
    domain: alpha-ops
    display_name: Alpha Bot
    class: operator
    policy_profile: manual
workers:
  - slug: host
    principal: alpha
    display_name: Host
    kind: workstation
    place: home
    control_class: root-controlled
    policy_profile: manual
assets:
  - slug: thing
    principal: alpha
    display_name: Thing
    kind: device
    worker: host
    place: home
    control_class: root-controlled
services:
  - slug: alpha-svc
    principal: alpha
    domain: alpha-ops
    bot: alpha-bot
    worker: host
    place: home
    display_name: Alpha Service
    kind: daemon
    policy_profile: manual
channels: []
people: []
"""


def test_load_registry_normalizes_and_summarizes(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(VALID_REGISTRY, encoding="utf-8")

    registry = estate_registry.load_registry(path)

    assert estate_registry.registry_summary(registry) == {
        "principals": 1,
        "policy_profiles": 1,
        "control_classes": 1,
        "domains": 1,
        "places": 1,
        "site_shortcuts": 1,
        "bots": 1,
        "workers": 1,
        "assets": 1,
        "services": 1,
        "channels": 0,
        "people": 0,
    }


def test_default_registry_publishes_dohio_topology() -> None:
    registry = estate_registry.load_registry(estate_registry.DEFAULT_TEMPLATE_PATH)
    workers = {item["slug"]: item for item in registry["workers"]}
    services = {item["slug"]: item for item in registry["services"]}

    assert workers["cloud-gw-ohio"]["hostname"] == "cloud-gw-ohio.tail94915.ts.net"
    assert services["dohio-topology"]["web_url"] == "https://dohio.home.arpa/"
    assert (
        services["dohio-topology"]["web_url_tailnet"]
        == "https://cloud-gw-ohio.tail94915.ts.net/"
    )
    assert services["switchyard-network-board"]["web_url"] == (
        "https://dohio.home.arpa/admin"
    )


def test_load_registry_rejects_duplicate_slugs(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(
        "principals:\n  - slug: alpha\n  - slug: alpha\npolicy_profiles: []\n"
        "control_classes: []\ndomains: []\nplaces: []\nsite_shortcuts: []\n"
        "bots: []\nworkers: []\nassets: []\nservices: []\nchannels: []\npeople: []\n",
        encoding="utf-8",
    )

    with pytest.raises(estate_registry.EstateRegistryError, match="duplicate slug"):
        estate_registry.load_registry(path)


def test_load_registry_rejects_unknown_reference(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(
        VALID_REGISTRY.replace("principal: alpha", "principal: beta", 1),
        encoding="utf-8",
    )

    with pytest.raises(
        estate_registry.EstateRegistryError, match="unknown principal `beta`"
    ):
        estate_registry.load_registry(path)


def test_init_registry_copies_template(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template = tmp_path / "registry.yaml.dist"
    template.write_text(VALID_REGISTRY, encoding="utf-8")
    monkeypatch.setattr(estate_registry, "DEFAULT_TEMPLATE_PATH", template)

    out = estate_registry.init_registry(tmp_path / "registry.yaml")

    assert out.exists()
    assert out.read_text(encoding="utf-8") == VALID_REGISTRY


def test_load_registry_rejects_unknown_site_shortcut_place(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(
        VALID_REGISTRY.replace("- home", "- beach", 1),
        encoding="utf-8",
    )

    with pytest.raises(
        estate_registry.EstateRegistryError,
        match="unknown site place `beach`",
    ):
        estate_registry.load_registry(path)
