from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_async_db, get_current_user
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
    User,
)


router = APIRouter(tags=["estate"])


def _serialize_model(obj, *, fields: tuple[str, ...]) -> dict:
    return {field: getattr(obj, field) for field in fields}


@router.get("/estate/summary")
async def estate_summary(
    db: Session = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    return {
        "principals": db.query(EstatePrincipal).count(),
        "domains": db.query(EstateDomain).count(),
        "bots": db.query(EstateBot).count(),
        "workers": db.query(EstateWorker).count(),
        "places": db.query(EstatePlace).count(),
        "assets": db.query(EstateAsset).count(),
        "services": db.query(EstateService).count(),
    }


@router.get("/estate/overview")
async def estate_overview(
    db: Session = Depends(get_async_db),
    _: User = Depends(get_current_user),
):
    principals = (
        db.query(EstatePrincipal).order_by(EstatePrincipal.display_name.asc()).all()
    )
    domains = db.query(EstateDomain).order_by(EstateDomain.display_name.asc()).all()
    bots = db.query(EstateBot).order_by(EstateBot.display_name.asc()).all()
    workers = db.query(EstateWorker).order_by(EstateWorker.display_name.asc()).all()
    places = db.query(EstatePlace).order_by(EstatePlace.display_name.asc()).all()
    assets = db.query(EstateAsset).order_by(EstateAsset.display_name.asc()).all()
    services = db.query(EstateService).order_by(EstateService.display_name.asc()).all()
    control_classes = (
        db.query(EstateControlClass).order_by(EstateControlClass.rank.desc()).all()
    )
    policy_profiles = (
        db.query(EstatePolicyProfile)
        .order_by(EstatePolicyProfile.display_name.asc())
        .all()
    )

    domain_names = {item.id: item.display_name for item in domains}
    bot_names = {item.id: item.display_name for item in bots}
    worker_names = {item.id: item.display_name for item in workers}
    place_names = {item.id: item.display_name for item in places}
    control_class_names = {item.id: item.display_name for item in control_classes}
    policy_profile_map = {
        item.id: {"name": item.display_name, "mode": item.mode}
        for item in policy_profiles
    }

    domains_by_principal = defaultdict(list)
    bots_by_principal = defaultdict(list)
    workers_by_principal = defaultdict(list)
    places_by_principal = defaultdict(list)
    assets_by_principal = defaultdict(list)
    services_by_principal = defaultdict(list)

    for item in domains:
        row = _serialize_model(
            item,
            fields=(
                "id",
                "slug",
                "display_name",
                "kind",
                "default_policy_profile_id",
            ),
        )
        policy = policy_profile_map.get(item.default_policy_profile_id) or {}
        row["default_policy_profile_name"] = policy.get("name")
        row["default_policy_mode"] = policy.get("mode")
        domains_by_principal[item.principal_id].append(row)
    for item in bots:
        row = _serialize_model(
            item,
            fields=(
                "id",
                "slug",
                "display_name",
                "class_name",
                "domain_id",
                "policy_profile_id",
            ),
        )
        row["domain_name"] = domain_names.get(item.domain_id)
        policy = policy_profile_map.get(item.policy_profile_id) or {}
        row["policy_profile_name"] = policy.get("name")
        row["policy_mode"] = policy.get("mode")
        bots_by_principal[item.principal_id].append(row)
    for item in workers:
        row = _serialize_model(
            item,
            fields=(
                "id",
                "slug",
                "display_name",
                "kind",
                "place_id",
                "control_class_id",
                "policy_profile_id",
            ),
        )
        row["place_name"] = place_names.get(item.place_id)
        row["control_class_name"] = control_class_names.get(item.control_class_id)
        policy = policy_profile_map.get(item.policy_profile_id) or {}
        row["policy_profile_name"] = policy.get("name")
        row["policy_mode"] = policy.get("mode")
        workers_by_principal[item.principal_id].append(row)
    for item in places:
        places_by_principal[item.principal_id].append(
            _serialize_model(
                item, fields=("id", "slug", "display_name", "kind", "parent_place_id")
            )
        )
    for item in assets:
        row = _serialize_model(
            item,
            fields=(
                "id",
                "slug",
                "display_name",
                "kind",
                "place_id",
                "worker_id",
                "control_class_id",
            ),
        )
        row["place_name"] = place_names.get(item.place_id)
        row["worker_name"] = worker_names.get(item.worker_id)
        row["control_class_name"] = control_class_names.get(item.control_class_id)
        assets_by_principal[item.principal_id].append(row)
    for item in services:
        row = _serialize_model(
            item,
            fields=(
                "id",
                "slug",
                "display_name",
                "kind",
                "domain_id",
                "bot_id",
                "worker_id",
                "place_id",
                "policy_profile_id",
                "web_url",
                "web_url_tailnet",
                "console_url",
                "console_url_tailnet",
            ),
        )
        row["domain_name"] = domain_names.get(item.domain_id)
        row["bot_name"] = bot_names.get(item.bot_id)
        row["worker_name"] = worker_names.get(item.worker_id)
        row["place_name"] = place_names.get(item.place_id)
        policy = policy_profile_map.get(item.policy_profile_id) or {}
        row["policy_profile_name"] = policy.get("name")
        row["policy_mode"] = policy.get("mode")
        services_by_principal[item.principal_id].append(row)

    principal_rows = []
    for principal in principals:
        row = _serialize_model(
            principal,
            fields=("id", "slug", "display_name", "kind", "is_active"),
        )
        row["domains"] = domains_by_principal[principal.id]
        row["bots"] = bots_by_principal[principal.id]
        row["workers"] = workers_by_principal[principal.id]
        row["places"] = places_by_principal[principal.id]
        row["assets"] = assets_by_principal[principal.id]
        row["services"] = services_by_principal[principal.id]
        row["counts"] = {
            "domains": len(row["domains"]),
            "bots": len(row["bots"]),
            "workers": len(row["workers"]),
            "places": len(row["places"]),
            "assets": len(row["assets"]),
            "services": len(row["services"]),
        }
        principal_rows.append(row)

    return {
        "summary": {
            "principals": len(principals),
            "domains": len(domains),
            "bots": len(bots),
            "workers": len(workers),
            "places": len(places),
            "assets": len(assets),
            "services": len(services),
        },
        "principals": principal_rows,
    }
