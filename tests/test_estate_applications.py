"""Behavioral coverage for ownership-preserving discovery and health joins."""

from datetime import datetime, timezone

import pytest

from app.services import estate_applications as estate

NOW = datetime(2026, 9, 14, 20, tzinfo=timezone.utc)
STAMP = NOW.isoformat()


def fixture():
    catalog = {
        "actors": [
            {
                "id": "ranger",
                "aliases": ["scout"],
                "preferred_operator_account": "openbrand",
            }
        ],
        "applications": [
            {
                "id": "scout",
                "primary_tui": "ranger",
                "lifecycle": "managed",
                "dohio_surface_ids": ["scout-app"],
            },
            {
                "id": "pretty-bird",
                "account": "openbrand",
                "lifecycle": "retired",
                "dohio_surface_ids": ["pretty-bird"],
            },
        ],
    }
    snapshot = {
        "status": {
            "surface_health": {
                "generated_at": STAMP,
                "surfaces": [
                    {
                        "id": "scout-app",
                        "checked_at": STAMP,
                        "level": "bad",
                        "state": "http-failed",
                    },
                    {
                        "id": "pretty-bird",
                        "checked_at": STAMP,
                        "level": "ok",
                        "state": "http-ok",
                    },
                ],
            },
            "bot_heartbeats": {
                "bots": {"scout": {"seen_at": STAMP, "status": "online"}}
            },
        },
        "registry": {
            "files": {
                "services.json": {
                    "services": [
                        {
                            "id": "new-app",
                            "name": "New app",
                            "bots": ["wrong-owner"],
                            "status": "live",
                        }
                    ]
                }
            }
        },
    }
    return catalog, snapshot


def test_app_failure_is_independent_of_tui_and_retirement_wins():
    catalog, snapshot = fixture()
    result = estate.build_overview(catalog, snapshot, NOW)
    app, retired = result["applications"]
    assert app["operator_observation"]["health"] == "reachable"
    assert app["health"] == "degraded"
    assert app["account"] == "openbrand"
    assert retired["health"] == "retired"
    assert not retired["needs_attention"]
    assert result["discoveries"][0]["status"] == "needs-review"
    assert "health" not in catalog["applications"][0]


def test_stale_missing_and_future_times_never_show_healthy():
    for timestamp in [None, "broken", "2026-09-14T19:00:00Z", "2026-09-15T20:00:00Z"]:
        result = estate.observation({"level": "ok"}, timestamp, NOW)
        assert result["health"] in ("unknown", "stale")
    assert (
        estate.observation({"level": "ok", "monitored": False}, STAMP, NOW)["health"]
        == "unknown"
    )


def test_operator_heartbeat_alone_never_proves_app_health():
    catalog, snapshot = fixture()
    snapshot["status"]["surface_health"]["surfaces"] = []
    assert (
        estate.build_overview(catalog, snapshot, NOW)["applications"][0]["health"]
        == "unknown"
    )


def test_imported_policy_and_references():
    catalog = estate.load_catalog()
    apps = {a["id"]: a for a in catalog["applications"]}
    actors = {a["id"]: a for a in catalog["actors"]}
    assert len(apps) == len(catalog["applications"])
    for app in apps.values():
        assert not app.get("primary_tui") or app["primary_tui"] in actors
    assert actors["emerald-canopy"]["preferred_operator_account"] == "evergreen"
    assert actors["pefb"]["preferred_operator_account"] == "personal"
    assert apps["pretty-bird"]["lifecycle"] == "retired"
    for key in ["yhix-site", "yhix-bedrock", "yhix-keys", "artdrop", "tahoma"]:
        assert actors[apps[key]["primary_tui"]]["preferred_operator_account"] == "yhix"


def test_safe_links():
    for value in [
        "javascript:alert(1)",
        "//evil.example",
        "https://user:password@example.com",
    ]:
        assert estate.safe_url(value) is None
    assert estate.safe_url("/bot/scoutbot/") == "/bot/scoutbot/"


@pytest.mark.asyncio
async def test_upstream_failure_retains_last_snapshot_and_bounds_retry(monkeypatch):
    class Offline:
        async def __aenter__(self):
            raise estate.httpx.ConnectError("offline")

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(estate, "_cache", {"status": {"last": "known"}})
    monkeypatch.setattr(estate.httpx, "AsyncClient", lambda **kwargs: Offline())
    first = await estate.dohio_snapshot()
    second = await estate.dohio_snapshot()
    assert first["status"] == {"last": "known"}
    assert first["error"]
    assert first["attempt"] == second["attempt"]


def test_authenticated_application_endpoint(test_app, monkeypatch):
    async def offline():
        return {"error": "Unavailable"}

    monkeypatch.setattr(estate, "dohio_snapshot", offline)
    response = test_app.get("/api/v1/estate/applications")
    assert response.status_code == 200
    body = response.json()
    assert body["source"]["error"] == "Unavailable"
    assert (
        next(a for a in body["applications"] if a["id"] == "pretty-bird")["health"]
        == "retired"
    )


def test_dohio_fail_and_warning_vocabulary_is_not_unknown():
    assert estate.observation({"level": "fail"}, STAMP, NOW)["health"] == "degraded"
    assert estate.observation({"level": "warn"}, STAMP, NOW)["health"] == "attention"
    assert (
        estate.observation({"state": "scaled-to-zero"}, STAMP, NOW)["health"] == "idle"
    )


def test_stale_output_overrules_live_process_and_metrics_retain_source_time():
    catalog, snapshot = fixture()
    catalog["applications"][0]["dohio_surface_ids"] = []
    snapshot["app_observations"] = {
        "observations": [
            {
                "application": "scout",
                "id": "worker",
                "level": "ok",
                "checked_at": STAMP,
                "evidence_kind": "process",
            },
            {
                "application": "scout",
                "id": "output",
                "level": "ok",
                "checked_at": "2026-07-07T12:00:00Z",
                "metrics": [
                    {
                        "id": "tasks",
                        "value": 19,
                        "source_timestamp": "2026-07-07T12:00:00Z",
                    }
                ],
            },
        ]
    }
    app = estate.build_overview(catalog, snapshot, NOW)["applications"][0]
    assert app["health"] == "stale"
    assert app["triage"]["category"] == "stale-evidence"
    assert app["measured_metrics"][0]["status"] == "stale"


def test_runtime_capacity_is_not_end_to_end_health():
    catalog, snapshot = fixture()
    catalog["applications"][0]["dohio_surface_ids"] = []
    snapshot["app_observations"] = {
        "observations": [
            {
                "application": "scout",
                "id": "worker",
                "level": "ok",
                "checked_at": STAMP,
                "evidence_kind": "runtime",
            }
        ]
    }
    app = estate.build_overview(catalog, snapshot, NOW)["applications"][0]
    assert app["health"] == "runtime-only"
    assert app["needs_attention"]


def test_on_demand_and_retired_have_no_always_on_expectation():
    catalog, snapshot = fixture()
    catalog["applications"][0].update(dohio_surface_ids=[], monitoring_mode="on-demand")
    app = estate.build_overview(catalog, snapshot, NOW)["applications"][0]
    assert app["health"] == "on-demand"
    assert not app["needs_attention"]


def test_known_console_is_reconciled_without_becoming_an_app_signal():
    catalog, snapshot = fixture()
    catalog["actors"][0]["dohio_operator_surface_ids"] = ["ranger"]
    snapshot["registry"]["files"]["surfaces.json"] = {"surfaces": [{"id": "ranger"}]}
    result = estate.build_overview(catalog, snapshot, NOW)
    assert not any(d["id"] == "ranger" for d in result["discoveries"])
    assert all(o["id"] != "ranger" for o in result["applications"][0]["observations"])


def test_every_catalog_entry_has_an_actionable_review():
    for app in estate.load_catalog()["applications"]:
        assert app["coverage_review"]["category"]
        assert app["coverage_review"]["next_action"]
        assert app["coverage_review"]["reviewed_at"]
