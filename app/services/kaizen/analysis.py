"""Local-only Norllama boundary for proposal-only Kaizen shadow candidates."""

import hashlib
import ipaddress
import json
import re
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Callable
from urllib.parse import urlsplit

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.services.kaizen.store import DbKaizenStore, db_kaizen_store
from app.services.kaizen.types import (
    KAIZEN_CANDIDATE_SCHEMA,
    KAIZEN_EVIDENCE_SCHEMA,
    KaizenCandidateAction,
    KaizenCandidateRiskTier,
    KaizenConfig,
    KaizenShadowCandidatePayload,
    as_utc,
    utc_iso,
)
from app.services.norllama.proxy import invoke_task
from app.services.norllama.routing import route_task
from app.services.norllama.types import (
    NorllamaReceipt,
    NorllamaRoute,
    NorllamaTaskRequest,
)


ShadowInvoker = Callable[[NorllamaTaskRequest], NorllamaReceipt]
RouteResolver = Callable[[NorllamaTaskRequest], NorllamaRoute]

_MAX_PACKET_OBSERVATIONS = 8
_MAX_EXPIRY_SECONDS = 30 * 24 * 60 * 60
_SUSPICIOUS_TEXT_PATTERNS = (
    re.compile(
        r"\b(?:api[_ -]?key|secret|password|token|authorization|bearer|"
        r"credential|private key)\b",
        re.IGNORECASE,
    ),
    re.compile(r"https?://|www\.", re.IGNORECASE),
    re.compile(
        r"\b(?:curl|wget|ssh|scp|sftp|ftp|telnet|netcat|nc)\b|"
        r"\b\d{1,3}(?:\.\d{1,3}){3}\b|\.home\.arpa\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"`|\$\(|(?:^|\s)\$|(?:^|\s)(?:bash|sh|zsh|fish|powershell|cmd|"
        r"sudo|rm|cp|mv|chmod|chown|cat|sed|awk|grep|find|tee|python|"
        r"pip|npm|make|git|docker|kubectl)(?:\s|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:write|edit|modify|delete|create|apply|patch)\s+"
        r"(?:the\s+)?(?:file|files|path|directory|dir)\b",
        re.IGNORECASE,
    ),
)


_ALLOWED_TARGETS: dict[str, dict[str, Any]] = {
    "docs/dohio_host_bot_lifecycle_runbook.md": {
        "lane": "runbook",
        "target_type": "runbook",
        "actions": {"report", "prepare_diff"},
    },
    "docs/internal_ca_dohio_runbook.md": {
        "lane": "runbook",
        "target_type": "runbook",
        "actions": {"report", "prepare_diff"},
    },
    "scripts/agent_console_template/skills/uplink-benchmark/SKILL.md": {
        "lane": "skill",
        "target_type": "skill",
        "actions": {"report"},
    },
    "docs/connectors/mcp.md": {
        "lane": "mcp_docs",
        "target_type": "mcp",
        "actions": {"report"},
    },
    "docs/norllama_kaizen_control_loop_plan.md": {
        "lane": "control_plane",
        "target_type": "kaizen_policy",
        "actions": {"report"},
    },
}


class KaizenShadowAnalyzer:
    """Build and validate proposal-only local model shadow candidates."""

    def __init__(
        self,
        *,
        store: DbKaizenStore | None = None,
        invoker: ShadowInvoker | None = None,
        route_resolver: RouteResolver | None = None,
    ) -> None:
        self._store = store or db_kaizen_store
        self._invoker = invoker or invoke_task
        self._route_resolver = route_resolver or route_task
        self._active = 0
        self._active_lock = Lock()

    def analyze(
        self,
        db: Session,
        *,
        user_id: int,
        realm: str,
        source_tui: str,
        config: KaizenConfig,
        now: datetime,
    ) -> dict[str, Any]:
        """Run one bounded, proposal-only local shadow analysis attempt."""
        now = as_utc(now)
        scope_failure = config.scope_failure(realm=realm, source_tui=source_tui)
        if scope_failure:
            return {
                "state": "skipped",
                "reason": scope_failure,
                "effect": "none",
            }
        config_failure = config.candidate_shadow_failure()
        if config_failure:
            return {
                "state": "skipped",
                "reason": config_failure,
                "effect": "none",
            }

        evidence = self._evidence_packet(
            db,
            user_id=user_id,
            realm=realm,
            source_tui=source_tui,
            config=config,
            now=now,
        )
        evidence_refs = [item["ref"] for item in evidence]
        if not evidence:
            return self._record(
                db,
                user_id=user_id,
                realm=realm,
                source_tui=source_tui,
                state="skipped",
                reason="no_fresh_warning_evidence",
                evidence_refs=[],
                receipt=_safe_receipt(
                    status="not_invoked",
                    charged_tokens=0,
                    requested_max_tokens=0,
                ),
                now=now,
            )

        requested_max_tokens = self._available_tokens(
            db,
            user_id=user_id,
            realm=realm,
            config=config,
            now=now,
        )
        if requested_max_tokens <= 0:
            return self._record(
                db,
                user_id=user_id,
                realm=realm,
                source_tui=source_tui,
                state="skipped",
                reason="daily_token_budget_exhausted",
                evidence_refs=evidence_refs,
                receipt=_safe_receipt(
                    status="not_invoked",
                    charged_tokens=0,
                    requested_max_tokens=0,
                ),
                now=now,
            )
        if not self._acquire_slot(config):
            return self._record(
                db,
                user_id=user_id,
                realm=realm,
                source_tui=source_tui,
                state="skipped",
                reason="candidate_shadow_concurrency_limited",
                evidence_refs=evidence_refs,
                receipt=_safe_receipt(
                    status="not_invoked",
                    charged_tokens=0,
                    requested_max_tokens=requested_max_tokens,
                ),
                now=now,
            )

        try:
            request = _shadow_request(
                evidence=evidence,
                max_tokens=requested_max_tokens,
            )
            planned_route = self._route_resolver(request)
            if not _local_norllama_route(planned_route):
                return self._record(
                    db,
                    user_id=user_id,
                    realm=realm,
                    source_tui=source_tui,
                    state="rejected",
                    reason="planned_route_not_local_norllama",
                    evidence_refs=evidence_refs,
                    receipt=_safe_receipt(
                        status="not_invoked",
                        route=planned_route,
                        charged_tokens=0,
                        requested_max_tokens=requested_max_tokens,
                    ),
                    now=now,
                )

            _pin_local_endpoint(request, planned_route)
            try:
                receipt = self._invoker(request)
            except Exception:
                return self._record(
                    db,
                    user_id=user_id,
                    realm=realm,
                    source_tui=source_tui,
                    state="failed",
                    reason="local_invocation_failed",
                    evidence_refs=evidence_refs,
                    receipt=_safe_receipt(
                        status="failed",
                        route=planned_route,
                        charged_tokens=requested_max_tokens,
                        requested_max_tokens=requested_max_tokens,
                    ),
                    now=now,
                )

            if not isinstance(receipt, NorllamaReceipt):
                return self._record(
                    db,
                    user_id=user_id,
                    realm=realm,
                    source_tui=source_tui,
                    state="rejected",
                    reason="invalid_model_receipt",
                    evidence_refs=evidence_refs,
                    receipt=_safe_receipt(
                        status="invalid",
                        route=planned_route,
                        charged_tokens=requested_max_tokens,
                        requested_max_tokens=requested_max_tokens,
                    ),
                    now=now,
                )

            charged_tokens = max(
                requested_max_tokens, _reported_total_tokens(receipt.output)
            )
            safe_receipt = _safe_receipt(
                status=receipt.status,
                route=receipt.route,
                charged_tokens=charged_tokens,
                requested_max_tokens=requested_max_tokens,
                reported_total_tokens=_reported_total_tokens(receipt.output),
            )
            if not _local_norllama_route(receipt.route):
                return self._record(
                    db,
                    user_id=user_id,
                    realm=realm,
                    source_tui=source_tui,
                    state="rejected",
                    reason="returned_route_not_local_norllama",
                    evidence_refs=evidence_refs,
                    receipt=safe_receipt,
                    now=now,
                )
            if receipt.status != "completed":
                return self._record(
                    db,
                    user_id=user_id,
                    realm=realm,
                    source_tui=source_tui,
                    state="failed",
                    reason="local_model_not_completed",
                    evidence_refs=evidence_refs,
                    receipt=safe_receipt,
                    now=now,
                )

            payload, rejection_reason = _parse_candidate(
                receipt.output.get("text"), evidence=evidence, now=now
            )
            if payload is None:
                return self._record(
                    db,
                    user_id=user_id,
                    realm=realm,
                    source_tui=source_tui,
                    state="rejected",
                    reason=rejection_reason,
                    evidence_refs=evidence_refs,
                    receipt=safe_receipt,
                    now=now,
                )

            audit = self._store.record_shadow_outcome(
                db,
                user_id=user_id,
                realm=realm,
                source_tui=source_tui,
                state="validated",
                reason="candidate_validated",
                evidence_refs=list(payload.evidence_refs),
                receipt=safe_receipt,
                now=now,
            )
            fingerprint = _candidate_fingerprint(payload, evidence)
            candidate, persistence = self._store.save_shadow_candidate(
                db,
                user_id=user_id,
                realm=realm,
                source_tui=source_tui,
                payload=payload,
                fingerprint=fingerprint,
                model_receipt_ref=audit["action_id"],
                now=now,
            )
            return {
                "state": "stored" if candidate is not None else "suppressed",
                "reason": persistence,
                "candidate": candidate,
                "audit": audit,
                "effect": "none",
            }
        finally:
            self._release_slot()

    def _evidence_packet(
        self,
        db: Session,
        *,
        user_id: int,
        realm: str,
        source_tui: str,
        config: KaizenConfig,
        now: datetime,
    ) -> list[dict[str, Any]]:
        since = now - timedelta(seconds=config.candidate_evidence_max_age_seconds)
        observations = self._store.list_observations(
            db,
            user_id=user_id,
            realm=realm,
            since=since,
            until=now,
            limit=250,
        )
        packet: list[dict[str, Any]] = []
        for observation in observations:
            if observation.get("source_tui") not in {"", source_tui}:
                continue
            if str(observation.get("state") or "").lower() not in {
                "warning",
                "critical",
            }:
                continue
            observed_at = _parse_timestamp(observation.get("observed_at"))
            if (
                observed_at is None
                or observed_at > now
                or (now - observed_at).total_seconds()
                > config.candidate_evidence_max_age_seconds
            ):
                continue
            identifier = observation.get("id")
            if not isinstance(identifier, int) or identifier <= 0:
                continue
            packet.append(
                {
                    "ref": f"observation:{identifier}",
                    "kpi_id": str(observation.get("kpi_id") or "")[:128],
                    "source_type": str(observation.get("source_type") or "")[:128],
                    "source_tui": str(observation.get("source_tui") or "")[:128],
                    "definition_version": str(
                        observation.get("definition_version") or ""
                    )[:64],
                    "state": str(observation.get("state") or "")[:32],
                    "value_numeric": observation.get("value_numeric"),
                    "unit": str(observation.get("unit") or "")[:32],
                    "confidence": observation.get("confidence"),
                    "observed_at": utc_iso(observed_at),
                }
            )
            if len(packet) >= _MAX_PACKET_OBSERVATIONS:
                break
        return packet

    def _available_tokens(
        self,
        db: Session,
        *,
        user_id: int,
        realm: str,
        config: KaizenConfig,
        now: datetime,
    ) -> int:
        utc_day = now.astimezone(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        used = self._store.shadow_token_usage(
            db, user_id=user_id, realm=realm, since=utc_day
        )
        remaining = max(0, config.daily_norllama_token_budget - used)
        return min(config.candidate_shadow_max_tokens, remaining)

    def _acquire_slot(self, config: KaizenConfig) -> bool:
        with self._active_lock:
            if self._active >= config.candidate_shadow_max_concurrency:
                return False
            self._active += 1
            return True

    def _release_slot(self) -> None:
        with self._active_lock:
            self._active = max(0, self._active - 1)

    def _record(
        self,
        db: Session,
        *,
        user_id: int,
        realm: str,
        source_tui: str,
        state: str,
        reason: str,
        evidence_refs: list[str],
        receipt: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        audit = self._store.record_shadow_outcome(
            db,
            user_id=user_id,
            realm=realm,
            source_tui=source_tui,
            state=state,
            reason=reason,
            evidence_refs=evidence_refs,
            receipt=receipt,
            now=now,
        )
        return {
            "state": state,
            "reason": reason,
            "audit": audit,
            "effect": "none",
        }


def _shadow_request(
    *,
    evidence: list[dict[str, Any]],
    max_tokens: int,
) -> NorllamaTaskRequest:
    """Create a bounded request that cannot name arbitrary targets or routes."""
    targets = [
        {
            "target_ref": target_ref,
            "lane": policy["lane"],
            "target_type": policy["target_type"],
            "allowed_actions": sorted(policy["actions"]),
        }
        for target_ref, policy in _ALLOWED_TARGETS.items()
    ]
    instructions = {
        "task": "Return one proposal-only Kaizen shadow candidate.",
        "response_contract": {
            "schema": KAIZEN_CANDIDATE_SCHEMA,
            "must_be_exactly_one_json_object": True,
            "no_markdown": True,
        },
        "constraints": [
            "Use only the supplied evidence_refs and allowed targets.",
            "Use only report, or prepare_diff for an allowed runbook target.",
            "Do not include URLs, network instructions, commands, credentials, or secrets.",
            "The response is a proposal only and must not claim a change occurred.",
        ],
        "evidence_schema": KAIZEN_EVIDENCE_SCHEMA,
        "evidence": evidence,
        "allowed_targets": targets,
    }
    return NorllamaTaskRequest(
        kind="plan",
        input_text=json.dumps(instructions, separators=(",", ":"), sort_keys=True),
        route_policy={
            "provider": "norllama",
            "allow_cloud_proxy": False,
            "local_first": True,
            "max_tokens": max_tokens,
        },
        metadata={"phase": "kaizen_candidate_shadow", "effect": "none"},
    )


def _parse_candidate(
    raw_text: Any, *, evidence: list[dict[str, Any]], now: datetime
) -> tuple[KaizenShadowCandidatePayload | None, str]:
    """Parse the one supported JSON shape without attempting a model-output repair."""
    if not isinstance(raw_text, str):
        return None, "model_output_missing_text"
    try:
        loaded = json.loads(raw_text)
    except (TypeError, ValueError):
        return None, "model_output_invalid_json"
    if not isinstance(loaded, dict):
        return None, "model_output_not_object"
    try:
        payload = KaizenShadowCandidatePayload.parse_obj(loaded)
    except ValidationError:
        return None, "model_output_schema_invalid"

    target_policy = _ALLOWED_TARGETS.get(payload.target_ref)
    if target_policy is None:
        return None, "candidate_target_not_allowed"
    if (
        payload.lane.value != target_policy["lane"]
        or payload.target_type.value != target_policy["target_type"]
    ):
        return None, "candidate_target_lane_mismatch"
    if payload.proposal.allowed_action.value not in target_policy["actions"]:
        return None, "candidate_action_not_allowed"
    if (
        payload.proposal.allowed_action == KaizenCandidateAction.PREPARE_DIFF
        and payload.lane.value != "runbook"
    ):
        return None, "candidate_action_not_allowed"
    if payload.proposal.allowed_action not in {
        KaizenCandidateAction.REPORT,
        KaizenCandidateAction.PREPARE_DIFF,
    }:
        return None, "candidate_action_not_allowed"
    if (
        payload.proposal.allowed_action == KaizenCandidateAction.REPORT
        and payload.risk_tier != KaizenCandidateRiskTier.READ_ONLY
    ):
        return None, "candidate_risk_tier_not_allowed"
    if (
        payload.proposal.allowed_action == KaizenCandidateAction.PREPARE_DIFF
        and payload.risk_tier != KaizenCandidateRiskTier.PROPOSAL_ONLY
    ):
        return None, "candidate_risk_tier_not_allowed"

    expiry_at = as_utc(payload.proposal.expiry_at)
    expiry_seconds = (expiry_at - now).total_seconds()
    if not 0 < expiry_seconds <= _MAX_EXPIRY_SECONDS:
        return None, "candidate_expiry_invalid"
    packet_refs = {str(item["ref"]) for item in evidence}
    if not set(payload.evidence_refs).issubset(packet_refs):
        return None, "candidate_evidence_not_in_packet"
    for text in _candidate_text_fields(payload):
        if _unsafe_text(text):
            return None, "candidate_unsafe_text"
    return payload, ""


def _candidate_text_fields(payload: KaizenShadowCandidatePayload) -> list[str]:
    return [
        payload.evidence_summary,
        payload.proposal.summary,
        *payload.proposal.verification_plan,
    ]


def _unsafe_text(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SUSPICIOUS_TEXT_PATTERNS)


def _candidate_fingerprint(
    payload: KaizenShadowCandidatePayload, evidence: list[dict[str, Any]]
) -> str:
    evidence_by_ref = {str(item["ref"]): item for item in evidence}
    evidence_classes = sorted(
        {
            f"{str(evidence_by_ref[reference].get('kpi_id') or '')}:"
            f"{str(evidence_by_ref[reference].get('state') or '')}"
            for reference in payload.evidence_refs
        }
    )
    canonical = {
        "target_type": payload.target_type.value,
        "target_ref": payload.target_ref,
        "lane": payload.lane.value,
        "evidence_classes": evidence_classes,
    }
    encoded = json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode(
        "ascii"
    )
    return hashlib.sha256(encoded).hexdigest()


def _local_norllama_route(route: Any) -> bool:
    if not isinstance(route, NorllamaRoute):
        return False
    return bool(
        route.provider == "norllama"
        and route.local
        and not route.cloud_proxy
        and _local_endpoint(route.endpoint)
    )


def _pin_local_endpoint(request: NorllamaTaskRequest, route: NorllamaRoute) -> None:
    """Keep the invocation on the endpoint that passed the local-route gate."""
    request.route_policy["endpoint"] = route.endpoint


def _local_endpoint(endpoint: str) -> bool:
    try:
        parsed = urlsplit(endpoint if "://" in endpoint else f"//{endpoint}")
    except ValueError:
        return False
    host = (parsed.hostname or "").strip("[]").lower()
    if not host:
        return False
    if host == "localhost" or host.endswith(".home.arpa"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(address.is_private or address.is_loopback or address.is_link_local)


def _reported_total_tokens(output: Any) -> int:
    if not isinstance(output, dict):
        return 0
    usage = output.get("usage") if isinstance(output.get("usage"), dict) else {}
    for value in (
        output.get("total_tokens"),
        usage.get("total_tokens"),
        output.get("output_tokens"),
        usage.get("output_tokens"),
    ):
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return 0


def _safe_receipt(
    *,
    status: str,
    charged_tokens: int,
    requested_max_tokens: int,
    route: NorllamaRoute | None = None,
    reported_total_tokens: int = 0,
) -> dict[str, Any]:
    """Return the small audit shape allowed to outlive an invocation."""
    return {
        "schema": "norman.kaizen-shadow-receipt.v1",
        "status": str(status)[:32],
        "route": {
            "provider": route.provider if route is not None else "",
            "capability": route.capability if route is not None else "",
            "mode": route.mode if route is not None else "",
            "local": bool(route.local) if route is not None else False,
            "cloud_proxy": bool(route.cloud_proxy) if route is not None else False,
        },
        "usage": {
            "requested_max_tokens": max(0, int(requested_max_tokens)),
            "reported_total_tokens": max(0, int(reported_total_tokens)),
            "charged_tokens": max(0, int(charged_tokens)),
        },
    }


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


kaizen_shadow_analyzer = KaizenShadowAnalyzer()
