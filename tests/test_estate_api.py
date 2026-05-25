from __future__ import annotations

import pathlib

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


def test_estate_overview_endpoint_returns_grouped_principals(
    test_app, db, tmp_path: pathlib.Path
) -> None:
    _clear_estate(db)
    path = tmp_path / "registry.yaml"
    path.write_text(VALID_REGISTRY, encoding="utf-8")
    registry = estate_registry.load_registry(path)
    estate_sync.sync_registry(db, registry)

    response = test_app.get("/api/v1/estate/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["principals"] == 1
    assert payload["summary"]["services"] == 1
    assert payload["principals"][0]["slug"] == "alpha"
    assert payload["principals"][0]["services"][0]["slug"] == "alpha-svc"
    assert payload["principals"][0]["services"][0]["domain_name"] == "Ops"
    assert payload["principals"][0]["services"][0]["web_url"] == "http://alpha.local"
    assert (
        payload["principals"][0]["services"][0]["web_url_tailnet"]
        == "https://alpha.ts.net"
    )
    assert (
        payload["principals"][0]["services"][0]["console_url"]
        == "http://alpha.local/chat"
    )
    assert (
        payload["principals"][0]["services"][0]["console_url_tailnet"]
        == "https://alpha.ts.net/chat"
    )
    assert payload["principals"][0]["services"][0]["is_active"] is True
    assert (
        payload["principals"][0]["workers"][0]["control_class_name"]
        == "Root Controlled"
    )


def test_estate_summary_endpoint_returns_counts(
    test_app, db, tmp_path: pathlib.Path
) -> None:
    _clear_estate(db)
    path = tmp_path / "registry.yaml"
    path.write_text(VALID_REGISTRY, encoding="utf-8")
    registry = estate_registry.load_registry(path)
    estate_sync.sync_registry(db, registry)

    response = test_app.get("/api/v1/estate/summary")

    assert response.status_code == 200
    assert response.json() == {
        "principals": 1,
        "domains": 1,
        "bots": 1,
        "workers": 1,
        "places": 1,
        "assets": 1,
        "services": 1,
    }


def test_estate_overview_hides_retired_services(
    test_app, db, tmp_path: pathlib.Path
) -> None:
    _clear_estate(db)
    path = tmp_path / "registry.yaml"
    path.write_text(VALID_REGISTRY, encoding="utf-8")
    registry = estate_registry.load_registry(path)
    retired = {
        **registry["services"][0],
        "slug": "alpha-retired",
        "display_name": "Alpha Retired",
        "is_active": False,
    }
    registry["services"].append(retired)
    estate_sync.sync_registry(db, registry)

    overview = test_app.get("/api/v1/estate/overview")
    summary = test_app.get("/api/v1/estate/summary")

    assert overview.status_code == 200
    assert summary.status_code == 200
    assert [item["slug"] for item in overview.json()["principals"][0]["services"]] == [
        "alpha-svc"
    ]
    assert summary.json()["services"] == 1
