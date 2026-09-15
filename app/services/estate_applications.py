"""Join Norman-owned application intent with read-only DOHIO observations."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

CATALOG_PATH = Path(__file__).resolve().parents[2] / "db/estate/applications.json"
DOHIO_URL = os.environ.get("NORMAN_DOHIO_URL", "https://dohio.home.arpa").rstrip("/")
CACHE_SECONDS = 60
STALE_SECONDS = 600
OBSERVATIONS_PATH = Path("/var/lib/norman/state/application-observations.json")
_cache: dict[str, Any] = {}
_lock = asyncio.Lock()


def load_catalog() -> dict:
    """Load durable ownership; discovery never writes this file."""
    return json.loads(CATALOG_PATH.read_text())


def load_app_observations() -> dict:
    """Read the separate scheduled metadata collector without running SSH in requests."""
    try:
        data = json.loads(OBSERVATIONS_PATH.read_text())
        return data if isinstance(data.get("observations"), list) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def safe_url(value: Any) -> str | None:
    """Allow web destinations without credentials, plus local Norman paths."""
    if not isinstance(value, str):
        return None
    parts = urlsplit(value)
    if parts.username or parts.password or value.startswith("//"):
        return None
    if parts.scheme in ("https", "http") and parts.netloc:
        return value
    if not parts.scheme and value.startswith("/"):
        return value
    return None


def age_seconds(value: str | None, now: datetime) -> float | None:
    """Return age for an aware timestamp; absent or malformed times are unknown."""
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        age = (now - stamp).total_seconds()
        return age if age >= -60 else None
    except (ValueError, TypeError):
        return None


def observation(row: dict, timestamp: str | None, now: datetime) -> dict:
    """Keep endpoint reachability distinct from end-to-end application health."""
    stamp = row.get("checked_at") or row.get("seen_at") or timestamp
    age = age_seconds(stamp, now)
    level = row.get("level", "unknown")
    state = row.get("state") or row.get("status") or "unknown"
    if age is None:
        health = "unknown"
    elif age > row.get("max_age_seconds", STALE_SECONDS):
        health = "stale"
    elif row.get("monitored") is False:
        health = "unknown"
    elif state in ("scaled-to-zero", "idle"):
        health = "idle"
    elif level in ("bad", "fail", "critical") or state in (
        "offline",
        "failed",
        "degraded",
        "inactive",
    ):
        health = "degraded"
    elif level == "warn" or state == "attention":
        health = "attention"
    elif level == "ok" or state in ("online", "live"):
        health = "reachable"
    else:
        health = "unknown"
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "health": health,
        "state": state,
        "observed_at": stamp,
        "detail": row.get("detail") or row.get("reason"),
        "url": safe_url(row.get("url")),
        "evidence_kind": row.get("evidence_kind", "reachability"),
        "max_age_seconds": row.get("max_age_seconds", STALE_SECONDS),
        "metrics": row.get("metrics", []),
        "environment": row.get("environment"),
    }


async def dohio_snapshot() -> dict:
    """Bound concurrent refreshes; retain last observations on upstream failure."""
    async with _lock:
        if time.monotonic() - _cache.get("attempt", float("-inf")) < CACHE_SECONDS:
            return copy.deepcopy(_cache)
        _cache["attempt"] = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=8, follow_redirects=False, verify=ssl.create_default_context()
            ) as client:
                responses = await asyncio.gather(
                    *[
                        client.get(f"{DOHIO_URL}/api/{path}")
                        for path in ("status", "registry")
                    ]
                )
            for response in responses:
                response.raise_for_status()
            status, registry = (response.json() for response in responses)
            if not isinstance(status.get("surface_health", {}).get("surfaces"), list):
                raise ValueError("Invalid DOHIO status shape")
            if not isinstance(registry.get("files"), dict):
                raise ValueError("Invalid DOHIO registry shape")
            _cache.update(
                status=status,
                registry=registry,
                error=None,
                fetched_at=datetime.now(timezone.utc).isoformat(),
            )
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            _cache["error"] = (
                "DOHIO refresh unavailable; retained observations may be stale."
            )
        return copy.deepcopy(_cache)


def app_observations(app: dict, status: dict, now: datetime) -> list[dict]:
    """Bind only explicitly assigned application signals."""
    observations = []
    for field, section, collection in [
        ("dohio_service_ids", "estate_services", "services"),
        ("dohio_surface_ids", "surface_health", "surfaces"),
    ]:
        source = status.get(section, {})
        rows = {row["id"]: row for row in source.get(collection, [])}
        for key in app.get(field, []):
            if key in rows:
                observations.append(
                    observation(rows[key], source.get("generated_at"), now)
                )
            else:
                observations.append(
                    observation({"id": key, "state": "missing"}, None, now)
                )
    for row in status.get("application_observations", []):
        if row.get("application") == app["id"]:
            observations.append(observation(row, None, now))
    return observations


def enrich_application(app: dict, actor: dict, status: dict, now: datetime) -> None:
    """Attach observations without changing the declared owner or lifecycle."""
    app["account"] = app.get("account") or actor.get("preferred_operator_account")
    app["account_basis"] = actor.get("account_policy_basis", app.get("ownership_basis"))
    app["fallback"] = actor.get("allowed_operator_fallback")
    app["console_url"] = safe_url(actor.get("console_url"))
    heartbeats = status.get("bot_heartbeats", {}).get("bots", {})
    ids = [actor.get("id"), *actor.get("aliases", [])]
    heartbeat = next((heartbeats[k] for k in ids if k in heartbeats), {})
    app["operator_observation"] = observation(heartbeat, None, now)
    observations = app_observations(app, status, now)
    app["observations"] = observations
    app["web_url"] = safe_url(app.get("web_url")) or next(
        (o["url"] for o in observations if o["url"]), None
    )
    healths = [o["health"] for o in observations]
    if app.get("lifecycle") in ("retired", "archived", "planned"):
        app["health"] = app["lifecycle"]
    else:
        app["health"] = next(
            (h for h in ("degraded", "stale", "attention", "unknown") if h in healths),
            "reachable" if healths else "unknown",
        )
    app["needs_attention"] = app["health"] not in (
        "retired",
        "archived",
        "planned",
    ) and (app["health"] != "reachable" or not app.get("primary_tui"))
    app["kpi_coverage"] = {"bound": 0, "total": len(app.get("kpi_contracts", []))}


def classify_coverage(app: dict, now: datetime | None = None) -> None:
    """Explain unavailable evidence, separating monitoring gaps from known failures."""
    health = app["health"]
    review = app.get("coverage_review", {})
    reason = review.get("category", "no-check")
    next_action = review.get(
        "next_action", "Bind an application-specific check and confirm its cadence."
    )
    if app.get("monitoring_mode") == "paused":
        app["health"] = "paused"
        app["needs_attention"] = False
        reason = "paused"
        next_action = "Intentionally paused; resume only on operator instruction."
    elif health in ("retired", "archived", "planned"):
        reason = health
        next_action = "No active-runtime health obligation."
    elif not app.get("primary_tui"):
        reason = "owner-unassigned"
        next_action = (
            "Assign a responsible TUI; keep the confirmed account classification."
        )
    elif health == "degraded":
        reason = "check-failed"
    elif health == "stale":
        reason = "stale-evidence"
    elif health == "attention":
        reason = "partial-coverage"
    elif any(o["state"] == "observer-unavailable" for o in app["observations"]):
        reason = "observer-unavailable"
        next_action = "Restore collector SSH/SSO access or resource visibility; do not treat this as an app outage."
    elif health == "reachable":
        runtime_only = all(
            o["evidence_kind"] in ("runtime", "process") for o in app["observations"]
        )
        reason = "runtime-only" if runtime_only else "observed"
        if runtime_only:
            app["health"] = "runtime-only"
            app["needs_attention"] = True
        next_action = review.get(
            "next_action",
            "Add output or workflow evidence where only process/reachability checks exist.",
        )
    elif app.get("monitoring_mode") == "on-demand":
        reason = "on-demand"
        app["health"] = "on-demand"
        app["needs_attention"] = False
    record_coverage(app, reason, next_action, now)


def record_coverage(
    app: dict, reason: str, next_action: str, now: datetime | None
) -> None:
    """Attach the owner action and measured KPI evidence after classification."""
    review = app.get("coverage_review", {})
    app["triage"] = {
        "category": reason,
        "owner": app.get("primary_tui") or "unassigned",
        "next_action": next_action,
        "evidence": review.get("evidence"),
        "reviewed_at": review.get("reviewed_at"),
    }
    app["measured_metrics"] = collected_metrics(app, now or datetime.now(timezone.utc))
    bind_kpis(app)


def collected_metrics(app: dict, now: datetime) -> list[dict]:
    """Keep measured values attached to source freshness and environment."""
    return [
        {
            **metric,
            "status": metric_status(metric, row, now),
            "source": row["id"],
            "environment": row.get("environment"),
        }
        for row in app["observations"]
        for metric in row.get("metrics", [])
    ]


def metric_status(metric: dict, row: dict, now: datetime) -> str:
    """Use each metric's timestamp, even when the surrounding report is fresh."""
    age = age_seconds(metric.get("source_timestamp"), now)
    if age is None or metric.get("value") is None:
        return "unknown"
    if age > row.get("max_age_seconds", STALE_SECONDS):
        return "stale"
    return (
        "observed"
        if row["health"] in ("reachable", "degraded", "attention", "idle")
        else row["health"]
    )


def bind_kpis(app: dict) -> None:
    """Resolve explicit KPI bindings; a configured source is not a fresh value."""
    measured = {(m["source"], m["id"]): m for m in app["measured_metrics"]}
    bound = 0
    fresh = 0
    for contract in app.get("kpi_contracts", []):
        binding = contract.get("binding", {})
        key = (binding.get("observation_id"), binding.get("metric_id"))
        configured = all(key)
        bound += bool(configured)
        value = measured.get(key, {})
        status = value.get("status", "unknown")
        if value.get("value") is None:
            status = "unknown"
        contract["measurement"] = {**value, "status": status}
        fresh += status == "observed"
    app["kpi_coverage"] = {
        "bound": bound,
        "fresh": fresh,
        "total": len(app.get("kpi_contracts", [])),
    }


def unmatched_discoveries(
    apps: list[dict], snapshot: dict, actors: list[dict] = ()
) -> list[dict]:
    """Return unmatched records for review, never auto-promote them into apps."""
    mapped_services = {key for a in apps for key in a.get("dohio_service_ids", [])}
    mapped_surfaces = {key for a in apps for key in a.get("dohio_surface_ids", [])}
    mapped_surfaces.update(
        key for a in actors for key in a.get("dohio_operator_surface_ids", [])
    )
    for row in (
        snapshot.get("status", {}).get("estate_services", {}).get("services", [])
    ):
        if row.get("id") in mapped_services:
            mapped_surfaces.update(row.get("surfaces", []))
    files = snapshot.get("registry", {}).get("files", {})
    discoveries = []
    for filename, section, mapped in [
        ("services.json", "services", mapped_services),
        ("surfaces.json", "surfaces", mapped_surfaces),
    ]:
        for row in files.get(filename, {}).get(section, []):
            if row.get("id") not in mapped:
                discoveries.append(
                    {
                        "id": row.get("id"),
                        "kind": section,
                        "name": row.get("name"),
                        "inventory_status": row.get("status"),
                        "url": safe_url(row.get("url")),
                        "status": "needs-review",
                        "suggested_operators": row.get("bots", []),
                    }
                )
    return discoveries


def build_overview(catalog: dict, snapshot: dict, now: datetime | None = None) -> dict:
    """Reconcile explicit IDs, preserving owner policy and retired history."""
    now = now or datetime.now(timezone.utc)
    result = copy.deepcopy(catalog)
    actors = {a["id"]: a for a in result["actors"]}
    status = copy.deepcopy(snapshot.get("status", {}))
    status["application_observations"] = snapshot.get("app_observations", {}).get(
        "observations", []
    )
    for app in result["applications"]:
        enrich_application(app, actors.get(app.get("primary_tui"), {}), status, now)
        classify_coverage(app, now)
    result["discoveries"] = unmatched_discoveries(
        result["applications"], snapshot, result["actors"]
    )
    alerts = snapshot.get("status", {}).get("alerts", {})
    result["alerts"] = [
        {key: row.get(key) for key in ("id", "severity", "status", "title", "detail")}
        for row in alerts.get("items", [])
    ]
    result["source"] = {
        "name": "DOHIO",
        "fetched_at": snapshot.get("fetched_at"),
        "error": snapshot.get("error"),
        "refresh_seconds": CACHE_SECONDS,
        "application_collector_at": snapshot.get("app_observations", {}).get(
            "generated_at"
        ),
    }
    result["summary"] = {
        "applications": len(result["applications"]),
        "attention": sum(a["needs_attention"] for a in result["applications"]),
        "discoveries": len(result["discoveries"]),
    }
    return result
