"""Authenticated API for the disabled-by-default Kaizen KPI foundation."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ConfigDict, BaseModel, constr
from sqlalchemy.orm import Session

from app.api.deps import get_console_runtime_user, get_db
from app.core.config import settings
from app.models import User
from app.services.kaizen import db_kaizen_store, kaizen_broker
from app.services.kaizen.evidence import build_tui_observations
from app.services.kaizen.types import (
    KaizenCandidateLane,
    KaizenConfig,
    TuiIdentifier,
    TuiKpiSnapshot,
)


router = APIRouter(prefix="/kaizen", tags=["kaizen"])

RealmValue = constr(pattern=r"^[a-z0-9][a-z0-9/_-]{1,95}$")


class KaizenTickRequest(BaseModel):
    """One central broker evaluation request."""

    realm: RealmValue
    source_tui: TuiIdentifier

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


@router.get("/status")
async def get_kaizen_status(
    current_user: User = Depends(get_console_runtime_user),
):
    """Return the current no-mutation Kaizen configuration."""
    _ = current_user
    config = KaizenConfig.from_settings(settings)
    return {
        "schema": "norman.kaizen-status.v1",
        "phase": (
            "candidate_shadow" if config.candidate_shadow_enabled else "observe_only"
        ),
        "enabled": config.enabled,
        "observe_only": config.observe_only,
        "auto_actions_enabled": False,
        "allowed_realms": list(config.allowed_realms),
        "pilot_tui_ids": list(config.pilot_tui_ids),
        "candidate_shadow": {
            "enabled": config.candidate_shadow_enabled,
            "local_only": True,
            "api_only": True,
            "daily_norllama_token_budget": config.daily_norllama_token_budget,
            "max_tokens": config.candidate_shadow_max_tokens,
            "max_concurrency": config.candidate_shadow_max_concurrency,
            "admission_failure": config.candidate_shadow_failure(),
        },
        "prohibited": [
            "notifications",
            "automatic_actions",
            "target_mutations",
            "cloud_or_external_calls",
            "normal_inbox_delivery",
            "prepare",
            "apply",
        ],
    }


@router.post("/tui-snapshots")
async def ingest_tui_snapshot(
    snapshot: TuiKpiSnapshot,
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    """Persist only the fixed aggregate fields from an eligible pilot TUI."""
    config = KaizenConfig.from_settings(settings)
    failure = config.scope_failure(realm=snapshot.realm, source_tui=snapshot.source_tui)
    if failure:
        _raise_scope_failure(failure)
    observations = build_tui_observations(snapshot)
    stored = db_kaizen_store.record_observations(
        db, user_id=current_user.id, observations=observations
    )
    return {
        "schema": "norman.kaizen-kpi-ingest.v1",
        "realm": snapshot.realm,
        "source_tui": snapshot.source_tui,
        "observation_count": len(stored),
        "effect": "none",
    }


@router.post("/tick")
async def run_kaizen_tick(
    payload: KaizenTickRequest,
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    """Run one no-effect admission evaluation for the central broker."""
    config = KaizenConfig.from_settings(settings)
    return kaizen_broker.tick(
        db,
        user_id=current_user.id,
        realm=payload.realm,
        source_tui=payload.source_tui,
        config=config,
    )


@router.get("/kpis")
async def get_kaizen_kpis(
    realm: RealmValue = Query("personal/home"),
    source_tui: str = Query("", max_length=128),
    window_seconds: int = Query(86_400, ge=60, le=2_592_000),
    limit: int = Query(250, ge=1, le=1000),
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    """Return only realm-scoped persisted aggregate KPI observations."""
    config = KaizenConfig.from_settings(settings)
    _require_allowed_realm(config, realm)
    from datetime import timedelta

    from app.services.kaizen.types import utc_now

    now = utc_now()
    since = now - timedelta(seconds=window_seconds)
    items = db_kaizen_store.list_observations(
        db,
        user_id=current_user.id,
        realm=realm,
        source_tui=source_tui,
        since=since,
        until=now,
        limit=limit,
    )
    return {
        "schema": "norman.kaizen-kpis.v1",
        "realm": realm,
        "source_tui": source_tui or None,
        "window_seconds": window_seconds,
        "items": items,
    }


@router.get("/reports/latest")
async def get_latest_kaizen_report(
    kind: Literal["daily"] = Query("daily"),
    realm: RealmValue = Query("personal/home"),
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    """Return the latest API-only report preview for one allowed realm."""
    config = KaizenConfig.from_settings(settings)
    _require_allowed_realm(config, realm)
    report = db_kaizen_store.latest_report(
        db, user_id=current_user.id, realm=realm, kind=kind
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Kaizen report not found")
    return report


@router.get("/candidates")
async def get_shadow_kaizen_candidates(
    realm: RealmValue = Query("personal/home"),
    source_tui: str = Query("", max_length=128),
    lane: str = Query("", max_length=32),
    limit: int = Query(100, ge=1, le=250),
    current_user: User = Depends(get_console_runtime_user),
    db: Session = Depends(get_db),
):
    """Return only API-visible, realm-scoped proposal-only shadow candidates."""
    config = KaizenConfig.from_settings(settings)
    _require_allowed_realm(config, realm)
    if lane and lane not in {item.value for item in KaizenCandidateLane}:
        raise HTTPException(status_code=422, detail="Unsupported Kaizen candidate lane")
    items = db_kaizen_store.list_shadow_candidates(
        db,
        user_id=current_user.id,
        realm=realm,
        source_tui=source_tui,
        lane=lane,
        limit=limit,
    )
    return {
        "schema": "norman.kaizen-candidates.v1",
        "realm": realm,
        "source_tui": source_tui or None,
        "lane": lane or None,
        "status": "shadow",
        "visibility": "shadow_api_only",
        "items": items,
    }


def _require_allowed_realm(config: KaizenConfig, realm: str) -> None:
    if realm not in config.allowed_realms:
        raise HTTPException(status_code=403, detail="Kaizen realm is not allowed")


def _raise_scope_failure(reason: str) -> None:
    if reason in ("kaizen_disabled", "observe_only_required"):
        raise HTTPException(
            status_code=409, detail=f"Kaizen ingestion blocked: {reason}"
        )
    raise HTTPException(status_code=403, detail=f"Kaizen ingestion blocked: {reason}")
