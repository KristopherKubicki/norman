from __future__ import annotations

import json
import os
import pathlib

from app.services import tui_fleet_health
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


def test_estate_tui_fleet_health_endpoint_returns_missing_state(
    test_app, monkeypatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.setenv(
        "NORMAN_TUI_FLEET_HEALTH_JSON", str(tmp_path / "missing-health.json")
    )

    response = test_app.get("/api/v1/estate/tui-fleet-health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["status"] == "missing"
    assert payload["summary"]["fail"] == 0
    assert payload["issues"] == []


def test_estate_tui_fleet_health_endpoint_reads_doctor_state(
    test_app, monkeypatch, tmp_path: pathlib.Path
) -> None:
    path = tmp_path / "tui-fleet-doctor.json"
    path.write_text(
        json.dumps(
            {
                "available": True,
                "status": "warn",
                "checked_at": "2026-05-28T04:44:15Z",
                "expected_ui_version": "2026.06.01.7",
                "summary": {
                    "active": 30,
                    "expected": 30,
                    "fail": 0,
                    "warn": 1,
                    "hosts": 6,
                    "ok": True,
                },
                "hosts": [],
                "issues": [
                    {
                        "severity": "warn",
                        "host": "work-special",
                        "instance": "panelbot",
                        "check": "runtime",
                        "detail": "busy/running",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NORMAN_TUI_FLEET_HEALTH_JSON", str(path))

    response = test_app.get("/api/v1/estate/tui-fleet-health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["status"] == "warn"
    assert payload["summary"]["active"] == 30
    assert payload["summary"]["warn"] == 1
    assert payload["issues"][0]["instance"] == "panelbot"
    assert payload["source"]["age_seconds"] >= 0


def test_estate_tui_fleet_health_endpoint_warns_on_stale_doctor_state(
    test_app, monkeypatch, tmp_path: pathlib.Path
) -> None:
    path = tmp_path / "tui-fleet-doctor.json"
    path.write_text(
        json.dumps(
            {
                "available": True,
                "status": "ok",
                "checked_at": "2026-05-28T04:44:15Z",
                "summary": {
                    "active": 30,
                    "expected": 30,
                    "fail": 0,
                    "warn": 0,
                    "hosts": 6,
                    "ok": True,
                },
                "hosts": [],
                "issues": [],
            }
        ),
        encoding="utf-8",
    )
    os.utime(path, (1000, 1000))
    monkeypatch.setenv("NORMAN_TUI_FLEET_HEALTH_JSON", str(path))
    monkeypatch.setenv("NORMAN_TUI_FLEET_HEALTH_STALE_AFTER_SECONDS", "900")
    monkeypatch.setattr(tui_fleet_health.time, "time", lambda: 2000)

    response = test_app.get("/api/v1/estate/tui-fleet-health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["status"] == "warn"
    assert payload["summary"]["warn"] == 1
    assert payload["summary"]["ok"] is True
    assert payload["source"]["stale"] is True
    assert payload["source"]["age_seconds"] == 1000
    assert payload["issues"][0]["check"] == "freshness"
    assert "1000s old > 900s" in payload["issues"][0]["detail"]


def test_systems_page_fetches_tui_fleet_health() -> None:
    root = pathlib.Path(__file__).resolve().parents[1]
    template = (root / "app" / "templates" / "systems.html").read_text(encoding="utf-8")
    source = (root / "app" / "static" / "js" / "systems.js").read_text(encoding="utf-8")

    assert 'id="tui-fleet-health"' in template
    assert "/api/v1/estate/tui-fleet-health" in source
    assert "renderFleetHealth" in source


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


def test_estate_powers_endpoint_returns_effective_manifest(
    test_app, monkeypatch, tmp_path: pathlib.Path
) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(VALID_REGISTRY, encoding="utf-8")
    monkeypatch.setattr(estate_registry, "DEFAULT_REGISTRY_PATH", path)

    response = test_app.get("/api/v1/estate/powers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["power_classes"] == ["mouth", "purse", "seal", "key", "sword"]
    assert payload["enforcement_gates"]["key"]["gate"] == "secret and system access"
    service = next(item for item in payload["items"] if item["slug"] == "alpha-svc")
    assert service["section"] == "services"
    assert service["powers"]["mouth"]["level"] == "operator-approved"
    assert service["powers"]["mouth"]["revoker"] == "norman"
    assert service["powers"]["purse"]["level"] == "none"
    assert service["powers"]["key"]["lease_source"] == "Norman Keys"
    assert service["powers"]["key"]["revoker"] == "norman-keys"
    assert service["issues"] == []
    assert payload["summary"]["active_power_counts"]["seal"] >= 1
    assert payload["summary"]["revocation_tests"]["mouth"]["pending"] >= 1
    assert payload["summary"]["revocation_tests"]["key"]["pending"] >= 1
    assert payload["summary"]["fail"] == 0


def test_power_manifest_warns_when_active_mouth_has_no_revoker(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text(VALID_REGISTRY, encoding="utf-8")
    registry = estate_registry.load_registry(path)
    registry["policy_profiles"][0]["powers"]["mouth"] = "operator-approved"

    payload = estate_registry.power_manifest(registry)

    service = next(item for item in payload["items"] if item["slug"] == "alpha-svc")
    assert service["issues"] == [
        {
            "severity": "warn",
            "section": "services",
            "slug": "alpha-svc",
            "power": "mouth",
            "detail": "mouth is active without revoker",
        }
    ]
    assert payload["summary"]["warn"] >= 1


def test_estate_powers_endpoint_keeps_default_profiles_seal_denied(test_app) -> None:
    response = test_app.get("/api/v1/estate/powers")

    assert response.status_code == 200
    payload = response.json()
    manual = next(
        profile for profile in payload["profiles"] if profile["slug"] == "manual"
    )
    shared = next(
        profile for profile in payload["profiles"] if profile["slug"] == "shared"
    )
    auto = next(profile for profile in payload["profiles"] if profile["slug"] == "auto")
    assert manual["powers"]["seal"]["level"] == "none"
    assert shared["powers"]["seal"]["level"] == "none"
    assert auto["powers"]["seal"]["level"] == "none"
    norman = next(item for item in payload["items"] if item["slug"] == "norman")
    norman_service = next(
        item for item in payload["items"] if item["slug"] == "norman-service"
    )
    assert norman["powers"]["seal"]["level"] == "operator-approved"
    assert norman_service["powers"]["seal"]["level"] == "operator-approved"


def test_default_power_manifest_marks_purse_cost_surfaces(test_app) -> None:
    response = test_app.get("/api/v1/estate/powers")

    assert response.status_code == 200
    payload = response.json()
    by_slug = {item["slug"]: item for item in payload["items"]}

    expected = {
        "parkergale": "draft",
        "leadership-kpis": "draft",
        "infra": "operator-approved",
        "control-plane": "operator-approved",
        "work-special-home": "operator-approved",
        "networking": "limited",
        "cloudagent": "operator-approved",
    }
    for slug, level in expected.items():
        purse = by_slug[slug]["powers"]["purse"]
        assert purse["level"] == level
        assert purse["spend_cap"]
        assert purse["revoker"] == "norman"

    assert payload["summary"]["active_power_counts"]["purse"] >= len(expected)
    assert not [
        issue
        for issue in payload["issues"]
        if issue["power"] == "purse" and issue["severity"] == "fail"
    ]


def test_default_power_manifest_scopes_infra_active_sword_authority(test_app) -> None:
    response = test_app.get("/api/v1/estate/powers")

    assert response.status_code == 200
    payload = response.json()
    by_slug = {item["slug"]: item for item in payload["items"]}

    active_sword = [
        item for item in payload["items"] if item["powers"]["sword"]["level"] != "none"
    ]
    assert payload["summary"]["active_power_counts"]["sword"] == 3
    assert [item["slug"] for item in active_sword] == [
        "infra",
        "networking",
        "cloudagent",
    ]
    infra_sword = by_slug["infra"]["powers"]["sword"]
    assert infra_sword["level"] == "operator-approved"
    assert infra_sword["responsible_human"]
    assert "offboarding" in infra_sword["accountable_purpose"]
    assert "No autonomous termination" in " ".join(infra_sword["constraints"])
    netops_sword = by_slug["networking"]["powers"]["sword"]
    assert "network isolation" in netops_sword["accountable_purpose"]
    assert "No autonomous lockout" in " ".join(netops_sword["constraints"])
    cloudagent_sword = by_slug["cloudagent"]["powers"]["sword"]
    assert "cloud/IAM containment" in cloudagent_sword["accountable_purpose"]
    assert "No autonomous account disablement" in " ".join(
        cloudagent_sword["constraints"]
    )
    assert not [
        issue
        for issue in payload["issues"]
        if issue["power"] == "sword" and issue["severity"] == "fail"
    ]
