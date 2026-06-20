#!/usr/bin/env python3
"""Run a Norman Keys issue/revoke drill using a harmless dummy alias."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    SecretAlias,
    SecretAuditEvent,
    SecretPolicy,
    SecretProvider,
)
from app.schemas.secret_keys import SecretRequestCreate  # noqa: E402
from app.services.secret_keys import (  # noqa: E402
    create_secret_request,
    revoke_secret_lease,
)


PROVIDER_NAME = "norman-keys-drill-file"
ALIAS_NAME = "drill.read-only.key-revocation"
POLICY_NAME = "drill-read-only-key-revocation"
REQUESTER_ID = "research-analyst"
LANE = "read-only"
DRILL_SECRET_VALUE = "norman-keys-drill-nonsecret"
DEFAULT_SECRET_FILE = (
    REPO_ROOT / "tmp" / "norman-keys-drill" / "read-only-key-revocation.txt"
)


@dataclass(frozen=True)
class KeyRevocationDrillResult:
    ran_at: str
    alias: str
    requester_id: str
    lane: str
    provider: str
    request_id: int
    request_status: str
    lease_id: int
    lease_status: str
    issued_event_count: int
    revoked_event_count: int
    raw_secret_output: bool = False

    def as_jsonable(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _prepare_dummy_secret_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{DRILL_SECRET_VALUE}\n", encoding="utf-8")
    return path


def _upsert_provider(db: Session) -> SecretProvider:
    provider = (
        db.query(SecretProvider).filter(SecretProvider.name == PROVIDER_NAME).first()
    )
    if provider is None:
        provider = SecretProvider(
            name=PROVIDER_NAME,
            kind="file",
            enabled=True,
            config={},
        )
        db.add(provider)
    else:
        provider.kind = "file"
        provider.enabled = True
        provider.config = {}
    db.commit()
    db.refresh(provider)
    return provider


def _upsert_alias(
    db: Session, *, provider: SecretProvider, secret_file: Path
) -> SecretAlias:
    alias = db.query(SecretAlias).filter(SecretAlias.name == ALIAS_NAME).first()
    if alias is None:
        alias = SecretAlias(name=ALIAS_NAME)
        db.add(alias)
    alias.provider_id = provider.id
    alias.backend_ref = str(secret_file)
    alias.lane = LANE
    alias.enabled = True
    alias.default_ttl_seconds = 60
    alias.allow_raw_reveal = False
    alias.metadata_json = {
        "purpose": "Norman Keys revocation drill",
        "contains_real_secret": False,
        "safe_to_delete": True,
    }
    db.commit()
    db.refresh(alias)
    return alias


def _upsert_policy(db: Session, *, requester_id: str, lane: str) -> SecretPolicy:
    policy = db.query(SecretPolicy).filter(SecretPolicy.name == POLICY_NAME).first()
    if policy is None:
        policy = SecretPolicy(name=POLICY_NAME)
        db.add(policy)
    policy.requester_type = "agent"
    policy.requester_id = requester_id
    policy.lane = lane
    policy.secret_prefix = ALIAS_NAME
    policy.allowed_modes = ["inject"]
    policy.max_ttl_seconds = 60
    policy.approval_required = False
    policy.raw_reveal_allowed = False
    policy.allowed_hosts = []
    policy.reuse_window_seconds = 0
    policy.enabled = True
    db.commit()
    db.refresh(policy)
    return policy


def _count_lease_events(db: Session, *, lease_id: int, event_type: str) -> int:
    return (
        db.query(SecretAuditEvent)
        .filter(
            SecretAuditEvent.lease_id == lease_id,
            SecretAuditEvent.event_type == event_type,
        )
        .count()
    )


def run_key_revocation_drill(
    db: Session,
    *,
    user_id: int = 1,
    actor_id: int = 1,
    requester_id: str = REQUESTER_ID,
    lane: str = LANE,
    secret_file: Path = DEFAULT_SECRET_FILE,
) -> KeyRevocationDrillResult:
    secret_file = _prepare_dummy_secret_file(secret_file)
    provider = _upsert_provider(db)
    _upsert_alias(db, provider=provider, secret_file=secret_file)
    _upsert_policy(db, requester_id=requester_id, lane=lane)

    body = SecretRequestCreate(
        name=ALIAS_NAME,
        requested_mode="inject",
        requested_ttl_seconds=60,
        requester_type="agent",
        requester_id=requester_id,
        lane=lane,
        intent="revocation-drill",
        reason="Norman Keys read-only Key revocation drill",
    )
    request, lease, secret_value, provider_kind, warnings = create_secret_request(
        db,
        user_id=user_id,
        body=body,
    )
    if warnings:
        raise RuntimeError(f"Norman Keys drill returned warnings: {warnings}")
    if lease is None:
        raise RuntimeError("Norman Keys drill did not issue a lease")
    if request.status != "issued":
        raise RuntimeError(f"Norman Keys drill request status was {request.status}")
    if lease.status != "active":
        raise RuntimeError(f"Norman Keys drill lease status was {lease.status}")
    if secret_value != DRILL_SECRET_VALUE:
        raise RuntimeError("Norman Keys drill did not resolve the dummy secret")

    revoked = revoke_secret_lease(db, lease_id=lease.id, actor_id=actor_id)
    if revoked.status != "revoked":
        raise RuntimeError(f"Norman Keys drill revoke status was {revoked.status}")
    if revoked.revoked_at is None:
        raise RuntimeError("Norman Keys drill revoked lease has no revoked_at")

    issued_event_count = _count_lease_events(
        db, lease_id=lease.id, event_type="lease_issued"
    )
    revoked_event_count = _count_lease_events(
        db, lease_id=lease.id, event_type="revoked"
    )
    if issued_event_count < 1:
        raise RuntimeError("Norman Keys drill did not record lease_issued audit event")
    if revoked_event_count < 1:
        raise RuntimeError("Norman Keys drill did not record revoked audit event")

    return KeyRevocationDrillResult(
        ran_at=_utc_now(),
        alias=ALIAS_NAME,
        requester_id=requester_id,
        lane=lane,
        provider=provider_kind,
        request_id=request.id,
        request_status=request.status,
        lease_id=lease.id,
        lease_status=revoked.status,
        issued_event_count=issued_event_count,
        revoked_event_count=revoked_event_count,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument(
        "--secret-file",
        type=Path,
        default=DEFAULT_SECRET_FILE,
        help="Path for the harmless dummy secret file.",
    )
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--actor-id", type=int, default=1)
    parser.add_argument("--requester-id", default=REQUESTER_ID)
    parser.add_argument("--lane", default=LANE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        result = run_key_revocation_drill(
            db,
            user_id=args.user_id,
            actor_id=args.actor_id,
            requester_id=args.requester_id,
            lane=args.lane,
            secret_file=args.secret_file,
        )
    finally:
        db.close()

    if args.json:
        print(json.dumps(result.as_jsonable(), indent=2))
    else:
        print(
            "Norman Keys issue/revoke drill passed: "
            f"{result.alias} lease {result.lease_id} is {result.lease_status}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
