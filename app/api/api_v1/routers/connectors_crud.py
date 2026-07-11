from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import time
import requests

from app import crud, models
from app.connectors.connector_utils import connector_classes, get_connectors_data
from app.schemas import (
    ConnectorCreate,
    ConnectorUpdate,
    Connector,
    ConnectorBundleImportResult,
    ConnectorBundlePayload,
    ConnectorBundleRoutingRule,
    ConnectorInfo,
)
from app.schemas.connector_status import (
    ConnectorStatusHistoryEntry,
    ConnectorStatusHistoryResponse,
)
from app.api.deps import get_db, get_current_user
from app.core.config import settings
from app.models import User
from app.services.connector_health import connector_health
from app.services.connector_oauth import (
    create_pending_state,
    consume_pending_state,
    resolve_oauth_binding,
)

router = APIRouter(prefix="/connectors", tags=["connectors"])


def _connector_page_redirect(
    status_value: str, detail: str = "", connector_id: int = 0
):
    params = {"oauth": status_value}
    if detail:
        params["detail"] = detail
    if connector_id:
        params["connector_id"] = str(connector_id)
    return RedirectResponse(
        url=f"/connectors.html?{urlencode(params)}", status_code=303
    )


def _get_user_connector_or_404(db: Session, connector_id: int, user: User):
    connector = crud.connector.get(db, connector_id)
    if not connector or connector.user_id != user.id:
        raise HTTPException(status_code=404, detail="Connector not found")
    return connector


def _strip_oauth_fields(config: dict) -> dict:
    cleaned = dict(config)
    for key in list(cleaned.keys()):
        if key.startswith("oauth_"):
            cleaned.pop(key, None)
    return cleaned


def _normalized_label(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def _connector_key(
    name: Optional[str], connector_type: Optional[str]
) -> Tuple[str, str]:
    return (_normalized_label(name), _normalized_label(connector_type))


def _find_connector_reference(
    *,
    connector_name: Optional[str],
    connector_type: Optional[str],
    label: str,
    connectors_by_key: Dict[Tuple[str, str], models.Connector],
    connectors_by_name: Dict[str, List[models.Connector]],
) -> Optional[models.Connector]:
    normalized_name = _normalized_label(connector_name)
    normalized_type = _normalized_label(connector_type)
    if not normalized_name:
        return None
    if normalized_type:
        connector = connectors_by_key.get((normalized_name, normalized_type))
        if connector:
            return connector
        raise HTTPException(
            status_code=400,
            detail=(
                f'{label} connector "{connector_name}"'
                f" ({connector_type}) was not found"
            ),
        )
    matches = connectors_by_name.get(normalized_name, [])
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise HTTPException(
            status_code=400,
            detail=f'{label} connector "{connector_name}" was not found',
        )
    raise HTTPException(
        status_code=400,
        detail=(
            f'{label} connector "{connector_name}" is ambiguous; include connector_type'
        ),
    )


def _find_rule_bot(
    *,
    rule: ConnectorBundleRoutingRule,
    bots_by_id: Dict[int, models.Bot],
    bots_by_session_id: Dict[str, List[models.Bot]],
    bots_by_name: Dict[str, List[models.Bot]],
) -> models.Bot:
    session_id = _normalized_label(rule.bot_session_id)
    if session_id:
        matches = bots_by_session_id.get(session_id, [])
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise HTTPException(
                status_code=400,
                detail=(
                    f'Routing rule "{rule.name}" references an ambiguous bot session '
                    f'"{rule.bot_session_id}"'
                ),
            )
    bot_name = _normalized_label(rule.bot_name)
    if bot_name:
        matches = bots_by_name.get(bot_name, [])
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise HTTPException(
                status_code=400,
                detail=(
                    f'Routing rule "{rule.name}" references an ambiguous bot name '
                    f'"{rule.bot_name}"'
                ),
            )
    if rule.bot_id:
        bot = bots_by_id.get(int(rule.bot_id))
        if bot:
            return bot
    raise HTTPException(
        status_code=400,
        detail=(
            f'Routing rule "{rule.name}" references bot '
            f'"{rule.bot_session_id or rule.bot_name or rule.bot_id}" that was not found'
        ),
    )


def _validate_bundle(bundle: ConnectorBundlePayload) -> None:
    seen_connectors = set()
    for connector in bundle.connectors:
        key = _connector_key(connector.name, connector.connector_type)
        if not key[0] or not key[1]:
            raise HTTPException(
                status_code=400,
                detail="Bundle connectors require name and connector_type",
            )
        if key in seen_connectors:
            raise HTTPException(
                status_code=400,
                detail=(
                    f'Duplicate connector "{connector.name}" '
                    f"({connector.connector_type}) in bundle"
                ),
            )
        seen_connectors.add(key)

    seen_rules = set()
    for rule in bundle.routing_rules:
        key = _normalized_label(rule.name)
        if not key:
            raise HTTPException(
                status_code=400, detail="Bundle routing rules require a name"
            )
        if key in seen_rules:
            raise HTTPException(
                status_code=400,
                detail=f'Duplicate routing rule "{rule.name}" in bundle',
            )
        seen_rules.add(key)


@router.get("/statuses")
async def list_connector_statuses(
    response: Response,
    refresh: bool = Query(False),
    max_age_seconds: int = Query(120, ge=5, le=3600),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return connector health snapshots for the current user.

    This is designed to be called by the UI instead of N per-connector status calls.
    """

    response.headers["Cache-Control"] = "private, max-age=5, stale-while-revalidate=15"

    connectors = crud.connector.get_multi_by_user(db, current_user.id)
    connector_ids = [int(c.id) for c in connectors]
    if refresh and connector_ids:
        await connector_health.kick_all(connector_ids)

    now = time.time()
    rows = []
    for connector in connectors:
        snap = await connector_health.get_snapshot(int(connector.id))
        if not snap:
            await connector_health.kick(int(connector.id))
            rows.append(
                {
                    "connector_id": int(connector.id),
                    "connector_type": connector.connector_type,
                    "status": "unknown",
                    "checked_at": None,
                    "next_check_at": None,
                    "failures": 0,
                    "error": "",
                }
            )
            continue
        if snap.checked_at and (now - snap.checked_at) > max_age_seconds:
            await connector_health.kick(int(connector.id))
        rows.append(
            {
                "connector_id": snap.connector_id,
                "connector_type": snap.connector_type,
                "status": snap.status,
                "checked_at": snap.checked_at,
                "next_check_at": snap.next_check_at,
                "failures": snap.failures,
                "error": snap.error,
            }
        )

    return {"items": rows, "count": len(rows)}


@router.get("/statuses/history", response_model=ConnectorStatusHistoryResponse)
async def get_connector_status_history(
    connector_id: int = Query(..., ge=1),
    limit: int = Query(20, ge=1, le=100),
    error_limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    connector = _get_user_connector_or_404(db, connector_id, current_user)
    history_entries = await connector_health.get_history(int(connector.id), limit=limit)
    history = [
        ConnectorStatusHistoryEntry(**entry.__dict__) for entry in history_entries
    ]
    recent_errors = [
        ConnectorStatusHistoryEntry(**entry.__dict__)
        for entry in history_entries
        if entry.error or entry.status != "up"
    ][:error_limit]
    if not history:
        await connector_health.kick(int(connector.id))
    return ConnectorStatusHistoryResponse(
        connector_id=int(connector.id),
        connector_name=connector.name,
        connector_type=str(connector.connector_type),
        history=history,
        recent_errors=recent_errors,
    )


@router.get("/available", response_model=List[ConnectorInfo])
async def list_available_connectors(response: Response) -> List[ConnectorInfo]:
    """Return metadata about all available connector implementations."""
    response.headers["Cache-Control"] = (
        "private, max-age=300, stale-while-revalidate=600"
    )
    return get_connectors_data()


@router.get("/export", response_model=ConnectorBundlePayload)
async def export_connector_bundle(
    response: Response,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    response.headers["Cache-Control"] = "private, no-store"

    connectors = sorted(
        crud.connector.get_multi_by_user(db, current_user.id),
        key=lambda connector: (
            _normalized_label(connector.name),
            _normalized_label(connector.connector_type),
            int(connector.id),
        ),
    )
    rules = sorted(
        crud.routing.get_rules_by_user(db, current_user.id),
        key=lambda rule: (
            -int(rule.priority or 0),
            _normalized_label(rule.name),
            rule.id,
        ),
    )
    bots_by_id = {
        int(bot.id): bot for bot in crud.bot.get_bots_by_user_id(db, current_user.id)
    }
    connectors_by_id = {int(connector.id): connector for connector in connectors}

    payload = ConnectorBundlePayload(
        exported_at=datetime.now(timezone.utc),
        connectors=[
            {
                "name": connector.name,
                "connector_type": connector.connector_type,
                "config": _strip_oauth_fields(dict(connector.config or {})),
            }
            for connector in connectors
        ],
        routing_rules=[
            {
                "name": rule.name,
                "connector_name": (
                    connectors_by_id.get(int(rule.connector_id)).name
                    if rule.connector_id and int(rule.connector_id) in connectors_by_id
                    else None
                ),
                "connector_type": (
                    connectors_by_id.get(int(rule.connector_id)).connector_type
                    if rule.connector_id and int(rule.connector_id) in connectors_by_id
                    else rule.connector_type
                ),
                "destination_connector_name": (
                    connectors_by_id.get(int(rule.destination_connector_id)).name
                    if rule.destination_connector_id
                    and int(rule.destination_connector_id) in connectors_by_id
                    else None
                ),
                "destination_connector_type": (
                    connectors_by_id.get(
                        int(rule.destination_connector_id)
                    ).connector_type
                    if rule.destination_connector_id
                    and int(rule.destination_connector_id) in connectors_by_id
                    else None
                ),
                "bot_id": rule.bot_id,
                "bot_name": bots_by_id.get(int(rule.bot_id)).name
                if rule.bot_id and int(rule.bot_id) in bots_by_id
                else None,
                "bot_session_id": bots_by_id.get(int(rule.bot_id)).session_id
                if rule.bot_id and int(rule.bot_id) in bots_by_id
                else None,
                "match_type": rule.match_type,
                "match_value": rule.match_value,
                "priority": rule.priority,
                "is_active": bool(rule.is_active),
            }
            for rule in rules
        ],
    )
    return payload


@router.post("/import", response_model=ConnectorBundleImportResult)
async def import_connector_bundle(
    bundle: ConnectorBundlePayload,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if int(bundle.version or 0) != 1:
        raise HTTPException(status_code=400, detail="Unsupported bundle version")

    _validate_bundle(bundle)

    existing_connectors = crud.connector.get_multi_by_user(db, current_user.id)
    connectors_by_key = {
        _connector_key(connector.name, connector.connector_type): connector
        for connector in existing_connectors
    }
    connectors_by_name: Dict[str, List[models.Connector]] = defaultdict(list)
    for connector in existing_connectors:
        connectors_by_name[_normalized_label(connector.name)].append(connector)

    bots = crud.bot.get_bots_by_user_id(db, current_user.id)
    bots_by_id = {int(bot.id): bot for bot in bots}
    bots_by_session_id: Dict[str, List[models.Bot]] = defaultdict(list)
    bots_by_name: Dict[str, List[models.Bot]] = defaultdict(list)
    for bot in bots:
        if bot.session_id:
            bots_by_session_id[_normalized_label(bot.session_id)].append(bot)
        bots_by_name[_normalized_label(bot.name)].append(bot)

    existing_rules = crud.routing.get_rules_by_user(db, current_user.id)
    existing_rules_by_name: Dict[str, models.RoutingRule] = {}
    for rule in existing_rules:
        existing_rules_by_name.setdefault(_normalized_label(rule.name), rule)

    result = ConnectorBundleImportResult(version=1)
    warnings: List[str] = []
    if any(
        key.startswith("oauth_")
        for connector in bundle.connectors
        for key in (connector.config or {}).keys()
    ):
        warnings.append(
            "OAuth fields were stripped during import; reconnect those connectors after import."
        )

    try:
        for connector_in in bundle.connectors:
            config = _strip_oauth_fields(dict(connector_in.config or {}))
            key = _connector_key(connector_in.name, connector_in.connector_type)
            connector = connectors_by_key.get(key)
            if connector is None:
                connector = models.Connector(
                    name=connector_in.name,
                    connector_type=connector_in.connector_type,
                    config=config,
                    user_id=current_user.id,
                )
                db.add(connector)
                db.flush()
                connectors_by_key[key] = connector
                connectors_by_name[_normalized_label(connector.name)].append(connector)
                result.connectors_created += 1
                continue

            changed = False
            if connector.name != connector_in.name:
                connector.name = connector_in.name
                changed = True
            if connector.connector_type != connector_in.connector_type:
                connector.connector_type = connector_in.connector_type
                changed = True
            if dict(connector.config or {}) != config:
                connector.config = config
                changed = True
            if changed:
                db.add(connector)
                result.connectors_updated += 1

        for rule_in in bundle.routing_rules:
            source_connector = _find_connector_reference(
                connector_name=rule_in.connector_name,
                connector_type=rule_in.connector_type,
                label="Source",
                connectors_by_key=connectors_by_key,
                connectors_by_name=connectors_by_name,
            )
            destination_connector = _find_connector_reference(
                connector_name=rule_in.destination_connector_name,
                connector_type=rule_in.destination_connector_type,
                label="Destination",
                connectors_by_key=connectors_by_key,
                connectors_by_name=connectors_by_name,
            )
            if (
                rule_in.destination_connector_type
                and not rule_in.destination_connector_name
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f'Routing rule "{rule_in.name}" has a destination connector_type '
                        "without a destination connector_name"
                    ),
                )
            bot = _find_rule_bot(
                rule=rule_in,
                bots_by_id=bots_by_id,
                bots_by_session_id=bots_by_session_id,
                bots_by_name=bots_by_name,
            )
            connector_id = int(source_connector.id) if source_connector else None
            connector_type = (
                source_connector.connector_type
                if source_connector
                else rule_in.connector_type
            )
            destination_connector_id = (
                int(destination_connector.id) if destination_connector else None
            )
            if (
                connector_id
                and destination_connector_id
                and connector_id == destination_connector_id
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f'Routing rule "{rule_in.name}" resolves to the same source and '
                        "destination connector"
                    ),
                )

            existing_rule = existing_rules_by_name.get(_normalized_label(rule_in.name))
            if existing_rule is None:
                db.add(
                    models.RoutingRule(
                        user_id=current_user.id,
                        name=rule_in.name,
                        connector_id=connector_id,
                        connector_type=connector_type,
                        destination_connector_id=destination_connector_id,
                        bot_id=int(bot.id),
                        match_type=rule_in.match_type,
                        match_value=rule_in.match_value,
                        priority=int(rule_in.priority),
                        is_active=bool(rule_in.is_active),
                    )
                )
                result.routing_rules_created += 1
                continue

            changed = False
            for field, value in (
                ("name", rule_in.name),
                ("connector_id", connector_id),
                ("connector_type", connector_type),
                ("destination_connector_id", destination_connector_id),
                ("bot_id", int(bot.id)),
                ("match_type", rule_in.match_type),
                ("match_value", rule_in.match_value),
                ("priority", int(rule_in.priority)),
                ("is_active", bool(rule_in.is_active)),
            ):
                if getattr(existing_rule, field) != value:
                    setattr(existing_rule, field, value)
                    changed = True
            if changed:
                db.add(existing_rule)
                result.routing_rules_updated += 1

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result.warnings = warnings
    return result


@router.post("/", response_model=Connector, status_code=201)
async def create_connector(
    connector: ConnectorCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a connector entry.

    Args:
        connector: Connector data from the request body.
        db: Database session dependency.

    Returns:
        The newly created connector.

    Raises:
        HTTPException: If the connector type is invalid or creation fails.
    """
    if connector.connector_type not in connector_classes:
        raise HTTPException(status_code=400, detail="Invalid connector type")
    try:
        return crud.connector.create(db, obj_in=connector, user_id=current_user.id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=List[Connector])
async def get_connectors(
    db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    """Return all connectors.

    Args:
        db: Database session dependency.

    Returns:
        List of connectors.
    """

    connectors = crud.connector.get_multi_by_user(db, current_user.id)
    return connectors


@router.get("/{connector_id}", response_model=Connector)
async def get_connector(
    connector_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Fetch a connector by ID.

    Args:
        connector_id: Identifier of the connector to fetch.
        db: Database session dependency.

    Returns:
        The requested connector.

    Raises:
        HTTPException: If the connector does not exist.
    """

    connector = crud.connector.get(db, connector_id)
    if not connector or connector.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Connector not found")
    return connector


@router.put("/{connector_id}", response_model=Connector)
async def update_connector(
    connector_id: int,
    connector: ConnectorUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Update an existing connector.

    Args:
        connector_id: Identifier of the connector to update.
        connector: Updated connector values.
        db: Database session dependency.

    Returns:
        The updated connector instance.

    Raises:
        HTTPException: If the connector does not exist or update fails.
    """
    db_connector = crud.connector.get(db, connector_id)
    if not db_connector or db_connector.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Connector not found")
    try:
        return crud.connector.update(db, db_obj=db_connector, obj_in=connector)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{connector_id}", response_model=Connector)
async def delete_connector(
    connector_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Delete a connector by ID.

    Args:
        connector_id: Identifier of the connector to delete.
        db: Database session dependency.

    Returns:
        The deleted connector instance.

    Raises:
        HTTPException: If the connector does not exist.
    """

    connector = crud.connector.remove(db, connector_id)
    if not connector or connector.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Connector not found")
    return connector


@router.get("/oauth/start")
async def start_connector_oauth(
    request: Request,
    connector_type: str = Query(...),
    connector_id: int = Query(0),
    provider: str = Query(""),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Start connector-level OAuth and redirect to provider auth page."""
    if connector_type not in connector_classes:
        raise HTTPException(status_code=400, detail="Invalid connector type")

    if connector_id:
        connector = _get_user_connector_or_404(db, connector_id, current_user)
        if connector.connector_type != connector_type:
            raise HTTPException(status_code=400, detail="Connector type mismatch")
    else:
        connector = crud.connector.create(
            db,
            obj_in=ConnectorCreate(
                name=f"{connector_classes[connector_type].name} Connector",
                connector_type=connector_type,
                config={},
            ),
            user_id=current_user.id,
        )

    try:
        binding = resolve_oauth_binding(connector_type, provider=provider or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    selected_provider = str(binding["provider"])
    scopes = list(binding["scopes"])
    token_field = str(binding["token_field"])
    state = create_pending_state(
        user_id=current_user.id,
        connector_id=connector.id,
        connector_type=connector_type,
        provider=selected_provider,
        token_field=token_field,
    )

    if selected_provider == "google":
        redirect_uri = str(request.url_for("connector_oauth_google_callback"))
        query = {
            "client_id": settings.google_client_id,
            "response_type": "code",
            "scope": " ".join(scopes),
            "redirect_uri": redirect_uri,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(query)
        return RedirectResponse(url=auth_url, status_code=303)

    if selected_provider == "microsoft":
        redirect_uri = str(request.url_for("connector_oauth_microsoft_callback"))
        query = {
            "client_id": settings.microsoft_client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": " ".join(scopes),
            "state": state,
            "prompt": "select_account",
        }
        auth_url = (
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?"
            + urlencode(query)
        )
        return RedirectResponse(url=auth_url, status_code=303)

    raise HTTPException(status_code=400, detail="Unsupported OAuth provider")


@router.get("/oauth/callback/google", name="connector_oauth_google_callback")
async def connector_oauth_google_callback(
    request: Request,
    code: str = Query(""),
    state: str = Query(""),
    error: str = Query(""),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if error:
        return _connector_page_redirect("error", detail=error)
    if not code or not state:
        return _connector_page_redirect("error", detail="missing_code_or_state")
    try:
        pending = consume_pending_state(state, current_user.id)
    except ValueError as exc:
        return _connector_page_redirect("error", detail=str(exc))
    if pending.provider != "google":
        return _connector_page_redirect("error", detail="provider_mismatch")

    token_resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": str(request.url_for("connector_oauth_google_callback")),
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    if not token_resp.ok:
        return _connector_page_redirect("error", detail="token_exchange_failed")
    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return _connector_page_redirect("error", detail="missing_access_token")

    connector = _get_user_connector_or_404(db, pending.connector_id, current_user)
    config = dict(connector.config or {})
    config[pending.token_field] = access_token
    if token_data.get("refresh_token"):
        config["oauth_refresh_token"] = token_data["refresh_token"]
    if token_data.get("scope"):
        config["oauth_scopes"] = [
            scope for scope in str(token_data["scope"]).split() if scope
        ]
    if token_data.get("expires_in"):
        expires_at = datetime.now(timezone.utc).timestamp() + int(
            token_data["expires_in"]
        )
        config["oauth_expires_at"] = int(expires_at)
    config["oauth_provider"] = "google"
    config["oauth_connected_at"] = datetime.now(timezone.utc).isoformat()
    crud.connector.update(
        db,
        db_obj=connector,
        obj_in=ConnectorUpdate(config=config),
    )
    return _connector_page_redirect(
        "success", detail="google_connected", connector_id=connector.id
    )


@router.get("/oauth/callback/microsoft", name="connector_oauth_microsoft_callback")
async def connector_oauth_microsoft_callback(
    request: Request,
    code: str = Query(""),
    state: str = Query(""),
    error: str = Query(""),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if error:
        return _connector_page_redirect("error", detail=error)
    if not code or not state:
        return _connector_page_redirect("error", detail="missing_code_or_state")
    try:
        pending = consume_pending_state(state, current_user.id)
    except ValueError as exc:
        return _connector_page_redirect("error", detail=str(exc))
    if pending.provider != "microsoft":
        return _connector_page_redirect("error", detail="provider_mismatch")

    token_resp = requests.post(
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        data={
            "client_id": settings.microsoft_client_id,
            "client_secret": settings.microsoft_client_secret,
            "code": code,
            "redirect_uri": str(request.url_for("connector_oauth_microsoft_callback")),
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    if not token_resp.ok:
        return _connector_page_redirect("error", detail="token_exchange_failed")
    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return _connector_page_redirect("error", detail="missing_access_token")

    connector = _get_user_connector_or_404(db, pending.connector_id, current_user)
    config = dict(connector.config or {})
    config[pending.token_field] = access_token
    if token_data.get("refresh_token"):
        config["oauth_refresh_token"] = token_data["refresh_token"]
    if token_data.get("scope"):
        config["oauth_scopes"] = [
            scope for scope in str(token_data["scope"]).split() if scope
        ]
    if token_data.get("expires_in"):
        expires_at = datetime.now(timezone.utc).timestamp() + int(
            token_data["expires_in"]
        )
        config["oauth_expires_at"] = int(expires_at)
    config["oauth_provider"] = "microsoft"
    config["oauth_connected_at"] = datetime.now(timezone.utc).isoformat()
    crud.connector.update(
        db,
        db_obj=connector,
        obj_in=ConnectorUpdate(config=config),
    )
    return _connector_page_redirect(
        "success", detail="microsoft_connected", connector_id=connector.id
    )


@router.delete("/{connector_id}/oauth")
async def disconnect_connector_oauth(
    connector_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Clear OAuth metadata/tokens for a connector."""
    connector = _get_user_connector_or_404(db, connector_id, current_user)
    config = dict(connector.config or {})
    provider_was_set = bool(config.get("oauth_provider"))
    updated_config = _strip_oauth_fields(config)
    # Clear commonly tokenized fields only when OAuth had been used.
    if provider_was_set:
        for key in (
            "oauth_access_token",
            "token",
            "access_token",
            "app_password",
            "password",
            "client_secret",
        ):
            if key in updated_config and isinstance(updated_config.get(key), str):
                updated_config[key] = ""
    crud.connector.update(
        db,
        db_obj=connector,
        obj_in=ConnectorUpdate(config=updated_config),
    )
    return {"status": "disconnected", "connector_id": connector.id}
