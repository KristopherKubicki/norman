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
    bbs:
      role: network
      zone: network
      receive: true
      full_coverage: true
      cross_zone: false
      allow_private: false
      channels:
        - switchboard
        - network/*
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
        "bots": 1,
        "workers": 1,
        "assets": 1,
        "services": 1,
        "channels": 0,
        "people": 0,
    }


def test_load_registry_preserves_and_projects_bbs_policy(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(VALID_REGISTRY, encoding="utf-8")

    registry = estate_registry.load_registry(path)

    worker = registry["workers"][0]
    assert worker["bbs"]["role"] == "network"
    assert estate_registry.bbs_connector_config(worker) == {
        "bbs_acl_role": "network",
        "bbs_zone": "network",
        "bbs_receive": True,
        "bbs_channels": ["switchboard", "network/*"],
        "bbs_full_coverage": True,
        "bbs_cross_zone": False,
        "bbs_allow_private": False,
    }


def test_load_registry_rejects_invalid_bbs_policy(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(
        VALID_REGISTRY.replace("role: network", "role: everything", 1),
        encoding="utf-8",
    )

    with pytest.raises(estate_registry.EstateRegistryError, match="bbs role"):
        estate_registry.load_registry(path)


def test_load_registry_rejects_duplicate_slugs(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(
        "principals:\n  - slug: alpha\n  - slug: alpha\npolicy_profiles: []\n"
        "control_classes: []\ndomains: []\nplaces: []\nbots: []\nworkers: []\n"
        "assets: []\nservices: []\nchannels: []\npeople: []\n",
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
