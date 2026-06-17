from __future__ import annotations

import pathlib

import pytest

from app.models import (
    EstateAsset,
    EstateBot,
    EstateControlClass,
    EstateDomain,
    EstatePlace,
    EstatePolicyProfile,
    EstatePrincipal,
    EstateService,
    EstateWorker,
)
from app.services import estate_registry, estate_sync


VALID_REGISTRY = """
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
    allows_runtime_control: true
    allows_side_effects: true
    powers:
      mouth:
        level: operator-approved
        revoker: norman
        revocation_tested_at: pending
      purse: none
      seal: operator-approved
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
    web_url: http://alpha.local
    web_url_tailnet: https://alpha.ts.net
    console_url: http://alpha.local/chat
    console_url_tailnet: https://alpha.ts.net/chat
channels: []
people: []
"""


def _clear_estate(db) -> None:
    for model in (
        EstateService,
        EstateAsset,
        EstateWorker,
        EstateBot,
        EstatePlace,
        EstateDomain,
        EstateControlClass,
        EstatePolicyProfile,
        EstatePrincipal,
    ):
        db.query(model).delete()
    db.commit()


def _load_registry(tmp_path: pathlib.Path):
    path = tmp_path / "registry.yaml"
    path.write_text(VALID_REGISTRY, encoding="utf-8")
    return estate_registry.load_registry(path)


def test_sync_registry_inserts_seed_rows(db, tmp_path: pathlib.Path) -> None:
    _clear_estate(db)
    registry = _load_registry(tmp_path)

    summary = estate_sync.sync_registry(db, registry)

    assert summary["principals"] == {"inserted": 1, "updated": 0}
    assert summary["services"] == {"inserted": 1, "updated": 0}

    principal = db.query(EstatePrincipal).filter_by(slug="alpha").one()
    domain = db.query(EstateDomain).filter_by(slug="alpha-ops").one()
    bot = db.query(EstateBot).filter_by(slug="alpha-bot").one()
    worker = db.query(EstateWorker).filter_by(slug="host").one()
    asset = db.query(EstateAsset).filter_by(slug="thing").one()
    service = db.query(EstateService).filter_by(slug="alpha-svc").one()

    assert domain.principal_id == principal.id
    assert bot.domain_id == domain.id
    assert worker.principal_id == principal.id
    assert asset.worker_id == worker.id
    assert service.bot_id == bot.id
    assert service.worker_id == worker.id
    assert service.web_url == "http://alpha.local"
    assert service.web_url_tailnet == "https://alpha.ts.net"
    assert service.console_url == "http://alpha.local/chat"
    assert service.console_url_tailnet == "https://alpha.ts.net/chat"


def test_sync_registry_updates_existing_rows(db, tmp_path: pathlib.Path) -> None:
    _clear_estate(db)
    registry = _load_registry(tmp_path)
    estate_sync.sync_registry(db, registry)

    registry["services"][0]["display_name"] = "Alpha Service Updated"
    registry["services"][0]["is_active"] = False
    registry["workers"][0]["display_name"] = "Host Updated"

    summary = estate_sync.sync_registry(db, registry)

    assert summary["services"] == {"inserted": 0, "updated": 1}
    assert summary["workers"] == {"inserted": 0, "updated": 1}
    assert (
        db.query(EstateService).filter_by(slug="alpha-svc").one().display_name
        == "Alpha Service Updated"
    )
    assert db.query(EstateService).filter_by(slug="alpha-svc").one().is_active is False
    assert (
        db.query(EstateWorker).filter_by(slug="host").one().display_name
        == "Host Updated"
    )


def test_sync_registry_deactivates_services_removed_from_registry(
    db, tmp_path: pathlib.Path
) -> None:
    _clear_estate(db)
    registry = _load_registry(tmp_path)
    stale_service = dict(registry["services"][0])
    stale_service["slug"] = "stale-svc"
    stale_service["display_name"] = "Stale Service"
    registry["services"].append(stale_service)
    estate_sync.sync_registry(db, registry)

    registry["services"] = [
        service for service in registry["services"] if service["slug"] != "stale-svc"
    ]
    summary = estate_sync.sync_registry(db, registry)

    assert summary["services"] == {"inserted": 0, "updated": 1, "deactivated": 1}
    stale = db.query(EstateService).filter_by(slug="stale-svc").one()
    assert stale.is_active is False
    assert "no longer present" in stale.notes


def test_registry_rejects_unknown_power_class(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(
        VALID_REGISTRY.replace("      sword: none", "      orbital: full"),
        encoding="utf-8",
    )

    with pytest.raises(estate_registry.EstateRegistryError, match="unsupported power"):
        estate_registry.load_registry(path)
