"""Sync the machine-readable estate registry into database tables."""

from __future__ import annotations

import pathlib
from typing import Any, Callable, Dict

from sqlalchemy.orm import Session

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
from app.services import estate_registry


def load_runtime_registry(
    path: str | pathlib.Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if path is not None:
        return estate_registry.load_registry(path)
    runtime_path = estate_registry.DEFAULT_REGISTRY_PATH
    if pathlib.Path(runtime_path).expanduser().exists():
        return estate_registry.load_registry(runtime_path)
    return estate_registry.load_registry(estate_registry.DEFAULT_TEMPLATE_PATH)


def _get_by_slug(db: Session, model, slug: str):
    return db.query(model).filter(model.slug == slug).first()


def _upsert_section(
    db: Session,
    entries: list[dict[str, Any]],
    model,
    apply_values: Callable[[Any, dict[str, Any]], None],
) -> dict[str, int]:
    inserted = 0
    updated = 0
    for entry in entries:
        obj = _get_by_slug(db, model, entry["slug"])
        if obj is None:
            obj = model(slug=entry["slug"])
            db.add(obj)
            inserted += 1
        else:
            updated += 1
        apply_values(obj, entry)
    db.flush()
    return {"inserted": inserted, "updated": updated}


def _deactivate_missing_services(
    db: Session,
    registry_services: list[dict[str, Any]],
) -> int:
    registry_slugs = {
        str(item.get("slug") or "").strip()
        for item in registry_services
        if isinstance(item, dict)
    }
    if not registry_slugs:
        return 0

    deactivated = 0
    for service in db.query(EstateService).all():
        if service.slug in registry_slugs or service.is_active is False:
            continue
        service.is_active = False
        if not service.notes:
            service.notes = "Deactivated because this service is no longer present in the estate registry."
        deactivated += 1
    if deactivated:
        db.flush()
    return deactivated


def sync_registry(
    db: Session,
    registry: dict[str, list[dict[str, Any]]] | None = None,
    *,
    path: str | pathlib.Path | None = None,
) -> dict[str, dict[str, int]]:
    data = registry or load_runtime_registry(path)

    results: dict[str, dict[str, int]] = {}

    results["principals"] = _upsert_section(
        db,
        data["principals"],
        EstatePrincipal,
        lambda obj, item: _apply_principal(obj, item, db),
    )
    results["policy_profiles"] = _upsert_section(
        db,
        data["policy_profiles"],
        EstatePolicyProfile,
        _apply_policy_profile,
    )
    results["control_classes"] = _upsert_section(
        db,
        data["control_classes"],
        EstateControlClass,
        _apply_control_class,
    )
    results["domains"] = _upsert_section(
        db,
        data["domains"],
        EstateDomain,
        lambda obj, item: _apply_domain(obj, item, db),
    )
    results["places"] = _upsert_section(
        db,
        data["places"],
        EstatePlace,
        lambda obj, item: _apply_place(obj, item, db),
    )
    results["bots"] = _upsert_section(
        db,
        data["bots"],
        EstateBot,
        lambda obj, item: _apply_bot(obj, item, db),
    )
    results["workers"] = _upsert_section(
        db,
        data["workers"],
        EstateWorker,
        lambda obj, item: _apply_worker(obj, item, db),
    )
    results["assets"] = _upsert_section(
        db,
        data["assets"],
        EstateAsset,
        lambda obj, item: _apply_asset(obj, item, db),
    )
    results["services"] = _upsert_section(
        db,
        data["services"],
        EstateService,
        lambda obj, item: _apply_service(obj, item, db),
    )
    deactivated_services = _deactivate_missing_services(db, data["services"])
    if deactivated_services:
        results["services"]["deactivated"] = deactivated_services

    db.commit()
    return results


def _apply_principal(obj: EstatePrincipal, item: dict[str, Any], db: Session) -> None:
    obj.display_name = item["display_name"]
    obj.kind = item["kind"]
    obj.notes = item.get("notes")
    obj.is_active = bool(item.get("is_active", True))
    parent_slug = item.get("parent_principal")
    obj.parent_principal_id = (
        _get_by_slug(db, EstatePrincipal, parent_slug).id if parent_slug else None
    )


def _apply_policy_profile(obj: EstatePolicyProfile, item: dict[str, Any]) -> None:
    obj.display_name = item["display_name"]
    obj.mode = item["mode"]
    obj.requires_approval = bool(item.get("requires_approval", False))
    obj.allows_outbound_send = bool(item.get("allows_outbound_send", False))
    obj.allows_runtime_control = bool(item.get("allows_runtime_control", False))
    obj.allows_side_effects = bool(item.get("allows_side_effects", False))
    obj.notes = item.get("notes")


def _apply_control_class(obj: EstateControlClass, item: dict[str, Any]) -> None:
    obj.display_name = item["display_name"]
    obj.rank = int(item.get("rank", 0))
    obj.notes = item.get("notes")


def _apply_domain(obj: EstateDomain, item: dict[str, Any], db: Session) -> None:
    obj.principal_id = _get_by_slug(db, EstatePrincipal, item["principal"]).id
    obj.display_name = item["display_name"]
    obj.kind = item["kind"]
    policy_slug = item.get("default_policy_profile")
    obj.default_policy_profile_id = (
        _get_by_slug(db, EstatePolicyProfile, policy_slug).id if policy_slug else None
    )
    obj.notes = item.get("notes")


def _apply_place(obj: EstatePlace, item: dict[str, Any], db: Session) -> None:
    obj.principal_id = _get_by_slug(db, EstatePrincipal, item["principal"]).id
    obj.display_name = item["display_name"]
    obj.kind = item["kind"]
    parent_slug = item.get("parent_place")
    obj.parent_place_id = (
        _get_by_slug(db, EstatePlace, parent_slug).id if parent_slug else None
    )
    obj.notes = item.get("notes")


def _apply_bot(obj: EstateBot, item: dict[str, Any], db: Session) -> None:
    obj.principal_id = _get_by_slug(db, EstatePrincipal, item["principal"]).id
    obj.domain_id = _get_by_slug(db, EstateDomain, item["domain"]).id
    obj.display_name = item["display_name"]
    obj.class_name = item["class"]
    obj.policy_profile_id = _get_by_slug(
        db, EstatePolicyProfile, item["policy_profile"]
    ).id
    obj.owner_person_id = None
    obj.is_active = bool(item.get("is_active", True))
    obj.notes = item.get("notes")


def _apply_worker(obj: EstateWorker, item: dict[str, Any], db: Session) -> None:
    obj.principal_id = _get_by_slug(db, EstatePrincipal, item["principal"]).id
    obj.display_name = item["display_name"]
    obj.kind = item["kind"]
    obj.hostname = item.get("hostname")
    place_slug = item.get("place")
    obj.place_id = _get_by_slug(db, EstatePlace, place_slug).id if place_slug else None
    control_slug = item.get("control_class")
    obj.control_class_id = (
        _get_by_slug(db, EstateControlClass, control_slug).id if control_slug else None
    )
    policy_slug = item.get("policy_profile")
    obj.policy_profile_id = (
        _get_by_slug(db, EstatePolicyProfile, policy_slug).id if policy_slug else None
    )
    obj.is_active = bool(item.get("is_active", True))
    obj.notes = item.get("notes")


def _apply_asset(obj: EstateAsset, item: dict[str, Any], db: Session) -> None:
    obj.principal_id = _get_by_slug(db, EstatePrincipal, item["principal"]).id
    obj.display_name = item["display_name"]
    obj.kind = item["kind"]
    place_slug = item.get("place")
    obj.place_id = _get_by_slug(db, EstatePlace, place_slug).id if place_slug else None
    worker_slug = item.get("worker")
    obj.worker_id = (
        _get_by_slug(db, EstateWorker, worker_slug).id if worker_slug else None
    )
    control_slug = item.get("control_class")
    obj.control_class_id = (
        _get_by_slug(db, EstateControlClass, control_slug).id if control_slug else None
    )
    obj.is_active = bool(item.get("is_active", True))
    obj.notes = item.get("notes")


def _apply_service(obj: EstateService, item: dict[str, Any], db: Session) -> None:
    obj.principal_id = _get_by_slug(db, EstatePrincipal, item["principal"]).id
    obj.domain_id = _get_by_slug(db, EstateDomain, item["domain"]).id
    bot_slug = item.get("bot")
    obj.bot_id = _get_by_slug(db, EstateBot, bot_slug).id if bot_slug else None
    worker_slug = item.get("worker")
    obj.worker_id = (
        _get_by_slug(db, EstateWorker, worker_slug).id if worker_slug else None
    )
    place_slug = item.get("place")
    obj.place_id = _get_by_slug(db, EstatePlace, place_slug).id if place_slug else None
    obj.display_name = item["display_name"]
    obj.kind = item["kind"]
    policy_slug = item.get("policy_profile")
    obj.policy_profile_id = (
        _get_by_slug(db, EstatePolicyProfile, policy_slug).id if policy_slug else None
    )
    obj.web_url = item.get("web_url")
    obj.web_url_tailnet = item.get("web_url_tailnet")
    obj.console_url = item.get("console_url")
    obj.console_url_tailnet = item.get("console_url_tailnet")
    obj.start_command = item.get("start_command")
    obj.healthcheck = item.get("healthcheck")
    obj.is_active = bool(item.get("is_active", True))
    obj.notes = item.get("notes")
