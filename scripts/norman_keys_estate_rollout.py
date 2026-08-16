#!/usr/bin/env python3
"""Enroll estate hosts and prove the Norman Keys capability control path."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.models import (  # noqa: E402
    KeysCapability,
    KeysCapabilityPolicy,
    KeysHostEnrollment,
    User,
)
from app.schemas.secret_keys import (  # noqa: E402
    KeysCapabilityInvoke,
    KeysCapabilityRequestCreate,
)
from app.services.secret_keys import (  # noqa: E402
    create_capability_request,
    invoke_capability_lease,
    revoke_capability_lease,
)


CAPABILITY_NAME = "estate.keys.readiness"
ACTION = "verify"


@dataclass(frozen=True)
class HostSpec:
    host_id: str
    hostname: str
    fingerprint: str
    requester_id: str
    lane: str


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.resolve()}"


def _session_factory(path: Path):
    engine = create_engine(
        _database_url(path),
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _upsert_capability(db: Session) -> KeysCapability:
    capability = (
        db.query(KeysCapability).filter(KeysCapability.name == CAPABILITY_NAME).first()
    )
    if not capability:
        capability = KeysCapability(name=CAPABILITY_NAME)
        db.add(capability)
    capability.executor_kind = "receipt"
    capability.executor_ref = ""
    capability.secret_aliases = []
    capability.metadata_json = {
        "purpose": "estate capability enrollment and policy readiness proof",
        "side_effects": False,
    }
    capability.enabled = True
    db.commit()
    db.refresh(capability)
    return capability


def _upsert_host(
    db: Session, *, capability: KeysCapability, spec: HostSpec
) -> KeysHostEnrollment:
    enrollment = (
        db.query(KeysHostEnrollment)
        .filter(KeysHostEnrollment.host_id == spec.host_id)
        .first()
    )
    if not enrollment:
        enrollment = KeysHostEnrollment(host_id=spec.host_id)
        db.add(enrollment)
    enrollment.hostname = spec.hostname
    enrollment.identity_fingerprint = spec.fingerprint
    enrollment.requester_ids = [spec.requester_id]
    enrollment.capability_names = [CAPABILITY_NAME]
    enrollment.lanes = [spec.lane]
    enrollment.status = "active"
    enrollment.notes = "Receipt-only estate rollout; no secret delivery."

    policy_name = f"estate-keys-readiness-{spec.host_id}"
    policy = (
        db.query(KeysCapabilityPolicy)
        .filter(KeysCapabilityPolicy.name == policy_name)
        .first()
    )
    if not policy:
        policy = KeysCapabilityPolicy(name=policy_name)
        db.add(policy)
    policy.capability_id = capability.id
    policy.requester_type = "agent"
    policy.requester_id = spec.requester_id
    policy.lane = spec.lane
    policy.allowed_actions = [ACTION]
    policy.allowed_target_hosts = [spec.hostname]
    policy.max_ttl_seconds = 300
    policy.approval_required = False
    policy.enabled = True
    db.commit()
    db.refresh(enrollment)
    return enrollment


def _request(
    db: Session, *, user_id: int, spec: HostSpec, probe: str
):
    body = KeysCapabilityRequestCreate(
        capability=CAPABILITY_NAME,
        host_id=spec.host_id,
        identity_fingerprint=spec.fingerprint,
        requester_type="agent",
        requester_id=spec.requester_id,
        session_id="estate-rollout",
        lane=spec.lane,
        action=ACTION,
        parameters={"probe": probe},
        target_host=spec.hostname,
        reason="receipt-only rollout verification",
        requested_ttl_seconds=300,
    )
    return create_capability_request(
        db,
        user_id=user_id,
        body=body,
        asserted_fingerprint=spec.fingerprint,
    )


def _invoke(db: Session, *, spec: HostSpec, lease_uuid: str, probe: str):
    return invoke_capability_lease(
        db,
        lease_uuid=lease_uuid,
        body=KeysCapabilityInvoke(
            host_id=spec.host_id,
            identity_fingerprint=spec.fingerprint,
            parameters={"probe": probe},
        ),
        asserted_fingerprint=spec.fingerprint,
    )


def run_rollout(db_path: Path, specs: list[HostSpec]) -> dict:
    session_factory = _session_factory(db_path)
    with session_factory() as db:
        user = db.query(User).order_by(User.is_superuser.desc(), User.id.asc()).first()
        if not user:
            raise RuntimeError("Norman Keys rollout requires an existing Norman user")

        capability = _upsert_capability(db)
        for spec in specs:
            _upsert_host(db, capability=capability, spec=spec)

        host_results = []
        for spec in specs:
            _, used_lease, _, _ = _request(
                db, user_id=user.id, spec=spec, probe="estate-rollout-v1"
            )
            if not used_lease:
                raise RuntimeError(f"{spec.host_id}: readiness lease was not issued")
            receipt = _invoke(
                db,
                spec=spec,
                lease_uuid=used_lease.lease_uuid,
                probe="estate-rollout-v1",
            )

            _, revoked_lease, _, _ = _request(
                db, user_id=user.id, spec=spec, probe="estate-revocation-v1"
            )
            if not revoked_lease:
                raise RuntimeError(f"{spec.host_id}: revocation lease was not issued")
            revoke_capability_lease(
                db, lease_uuid=revoked_lease.lease_uuid, actor_id=user.id
            )
            revoked_rejected = False
            try:
                _invoke(
                    db,
                    spec=spec,
                    lease_uuid=revoked_lease.lease_uuid,
                    probe="estate-revocation-v1",
                )
            except HTTPException as exc:
                revoked_rejected = exc.status_code == 409
            if not revoked_rejected:
                raise RuntimeError(
                    f"{spec.host_id}: revoked capability lease was not rejected"
                )
            host_results.append(
                {
                    "host_id": spec.host_id,
                    "enrolled": True,
                    "invoke_status": receipt["status"],
                    "revoked_lease_rejected": True,
                }
            )

        return {
            "schema": "norman.keys.estate-rollout.v1",
            "capability": CAPABILITY_NAME,
            "executor_kind": "receipt",
            "secret_alias_count": 0,
            "hosts": host_results,
            "ready": all(
                row["invoke_status"] == "completed"
                and row["revoked_lease_rejected"]
                for row in host_results
            ),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--hal-fingerprint", required=True)
    parser.add_argument("--norman-fingerprint", required=True)
    parser.add_argument("--netops-fingerprint", required=True)
    args = parser.parse_args(argv)
    specs = [
        HostSpec(
            "hal",
            "hal.home.arpa",
            args.hal_fingerprint,
            "estate-keys-hal",
            "personal",
        ),
        HostSpec(
            "norman",
            "norman.home.arpa",
            args.norman_fingerprint,
            "estate-keys-norman",
            "infrastructure",
        ),
        HostSpec(
            "netops",
            "networking.home.arpa",
            args.netops_fingerprint,
            "estate-keys-netops",
            "network",
        ),
    ]
    report = run_rollout(args.db, specs)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
