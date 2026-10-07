"""Signed-broker rotation binding; no credential-bearing API result."""

import json
import logging
import os
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.encryption import EncryptionManager
from app.models.aws_key_rotation import AWSKeyRotation
from app.services.aws_key_rotation import Rotation
from app.services.aws_rotation_adapter import AWSRotationAdapter
from app.services.aws_rotation_lock import operation_lock
from app.services.aws_rotation_store import ACCOUNT, RotationError, RotationStore
from app.services.aws_rotation_transport import SSHHostTransport

STATE = Path("/var/lib/norman/state")
LOCK = STATE / "aws-source-rotation.lock"
PROBE = STATE / "aws-source-rotation-cipher-probe"
ACTIONS = {
    "dummy",
    "preflight",
    "cipher-test",
    "prepare",
    "distribute",
    "retire",
    "recover",
    "status",
}


def suppress_sdk_debug() -> None:
    """CreateAccessKey responses must never be emitted by SDK debug loggers."""
    names = list(logging.Logger.manager.loggerDict) + ["boto3", "botocore", "urllib3"]
    for name in names:
        if name.split(".")[0] in ("boto3", "botocore", "urllib3"):
            logging.getLogger(name).setLevel(logging.CRITICAL)


def cipher_test(cipher: EncryptionManager) -> str:
    """Persist a nonsecret probe for explicit verification after service restart."""
    expected = "norman-aws-rotation-cipher-probe-v1"
    with operation_lock(LOCK):
        if PROBE.exists():
            if cipher.decrypt(PROBE.read_text()) != expected:
                raise RotationError("rotation_cipher_probe_failed")
            return "cipher_verified"
        with open(
            PROBE, "x", opener=lambda path, flags: os.open(path, flags, 0o600)
        ) as stream:
            stream.write(cipher.encrypt(expected))
            stream.flush()
            os.fsync(stream.fileno())
    return "cipher_initialized"


def encrypted_backup(db: Session, cipher: EncryptionManager) -> None:
    """Keep a private encrypted-only recovery record outside the database."""
    row = db.get(AWSKeyRotation, ACCOUNT, populate_existing=True)
    if row is None or not row.encrypted_credential:
        raise RotationError("rotation_backup_source_missing")
    cipher.decrypt(row.encrypted_credential)
    destination = STATE / f"aws-source-rotation-{row.rotation_id}.encrypted.json"
    content = json.dumps(
        {
            "account_id": ACCOUNT,
            "rotation_id": row.rotation_id,
            "old_key_id": row.old_key_id,
            "new_key_id": row.new_key_id,
            "encrypted_credential": row.encrypted_credential,
        }
    )
    if destination.exists():
        if destination.read_text() != content:
            raise RotationError("rotation_backup_mismatch")
        return
    with open(
        destination, "x", opener=lambda path, flags: os.open(path, flags, 0o600)
    ) as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _execute(db: Session, action: str) -> dict[str, str]:
    """Construct adapters only inside the authorized server runtime."""
    suppress_sdk_debug()
    transport = SSHHostTransport()
    adapter = AWSRotationAdapter(transport)
    cipher = EncryptionManager()
    rotation = Rotation(RotationStore(db, cipher), adapter, LOCK)
    if action == "cipher-test":
        state = cipher_test(cipher)
    elif action in ("dummy", "preflight"):
        passed = transport.dummy() if action == "dummy" else adapter.preflight()
        if passed is not True:
            raise RotationError("rotation_preflight_failed")
        state = "transport_tested" if action == "dummy" else "preflight_passed"
    else:
        if action in ("prepare", "distribute", "retire"):
            if not PROBE.exists() or cipher_test(cipher) != "cipher_verified":
                raise RotationError("rotation_cipher_probe_required")
        if action == "distribute":
            encrypted_backup(db, cipher)
        status = (
            rotation.store.status()
            if action == "status"
            else getattr(rotation, action)()
        )
        if action == "prepare":
            encrypted_backup(db, cipher)
        state = status.state
    return {"account_id": ACCOUNT, "rotation_state": state}


def execute_rotation(
    db: Session, *, executor_ref: str, action: str, parameters: dict
) -> dict[str, str]:
    """Fixed binding, gated independently from the read-only readiness executor."""
    if (
        executor_ref != ACCOUNT
        or parameters != {"account_id": ACCOUNT}
        or action not in ACTIONS
    ):
        raise RotationError("rotation_request_not_allowed")
    if os.environ.get("NORMAN_KEYS_AWS_ROTATION_ENABLED") != "1":
        raise RotationError("rotation_disabled")
    try:
        return _execute(db, action)
    except Exception:
        raise RotationError("rotation_operation_failed") from None
