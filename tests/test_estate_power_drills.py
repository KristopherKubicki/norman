from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

from app.services import estate_registry


REGISTRY = """
principals:
  - slug: alpha
    display_name: Alpha
    kind: person
policy_profiles:
  - slug: manual
    display_name: Manual
    mode: manual
    requires_approval: true
    allows_outbound_send: true
    powers:
      mouth:
        level: operator-approved
        revoker: norman
        revocation_tested_at: pending
      purse: none
      seal: none
      key:
        level: scoped
        lease_source: Norman Keys
        revoker: norman-keys
        revocation_tested_at: pending
      sword: none
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
assets: []
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
    powers:
      seal:
        level: operator-approved
        revoker: norman
        revocation_tested_at: pending
  - slug: alpha-purse-svc
    principal: alpha
    domain: alpha-ops
    bot: alpha-bot
    worker: host
    place: home
    display_name: Alpha Purse Service
    kind: daemon
    policy_profile: manual
    powers:
      purse:
        level: draft
        spend_cap: no live spend
        revoker: norman
        revocation_tested_at: pending
channels: []
people: []
"""


def _load_drills_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "estate_power_drills.py"
    spec = importlib.util.spec_from_file_location("estate_power_drills", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["estate_power_drills"] = module
    spec.loader.exec_module(module)
    return module


def _write_registry(tmp_path: Path) -> Path:
    path = tmp_path / "registry.yaml"
    path.write_text(REGISTRY, encoding="utf-8")
    return path


def test_revocation_drill_targets_list_pending_declarations(tmp_path: Path) -> None:
    drills = _load_drills_module()
    path = _write_registry(tmp_path)
    registry = estate_registry.load_registry(path)

    targets = drills.revocation_drill_targets(registry)
    by_selector = {target.selector: target for target in targets}

    assert sorted(by_selector) == [
        "policy_profiles/manual/key",
        "policy_profiles/manual/mouth",
        "services/alpha-purse-svc/purse",
        "services/alpha-svc/seal",
    ]
    assert by_selector["policy_profiles/manual/mouth"].coverage == 4
    assert by_selector["policy_profiles/manual/key"].coverage == 4
    assert by_selector["services/alpha-purse-svc/purse"].coverage == 1
    assert by_selector["services/alpha-svc/seal"].coverage == 1


def test_record_revocation_test_updates_exact_declared_entry(tmp_path: Path) -> None:
    drills = _load_drills_module()
    path = _write_registry(tmp_path)

    entry = drills.record_revocation_test(
        path,
        section="policy_profiles",
        slug="manual",
        power="mouth",
        tested_at="2026-05-31",
        notes="revoked and restored outbound send path",
    )

    assert entry["revocation_tested_at"] == "2026-05-31"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    mouth = raw["policy_profiles"][0]["powers"]["mouth"]
    assert mouth["revocation_tested_at"] == "2026-05-31"
    assert mouth["revocation_test_notes"] == "revoked and restored outbound send path"

    registry = estate_registry.load_registry(path)
    pending_selectors = {
        target.selector for target in drills.revocation_drill_targets(registry)
    }
    assert "policy_profiles/manual/mouth" not in pending_selectors
    assert "policy_profiles/manual/key" in pending_selectors
