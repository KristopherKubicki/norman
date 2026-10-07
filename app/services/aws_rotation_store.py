"""Internal durable storage for the fixed personal AWS rotation.

Accepts an already configured cipher. This module never initializes encryption
configuration, reads credential files, logs material, or serves secret values.
No automatic expiry or deletion: interruption requires explicit reconciliation.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Callable, Protocol, TypeVar

from sqlalchemy.orm import Session

from app.models.aws_key_rotation import AWSKeyRotation

ACCOUNT = "970651210182"
OLD_KEY = "AKIA6D72SCHDJMCBQ2OX"
ALIAS = "cloudagent/aws/gmail"
T = TypeVar("T")


class RotationError(Exception):
    """Fixed safe error, with no SDK, SQL, or credential contents."""


class Cipher(Protocol):
    """Existing runtime cipher; key lifecycle is owned by deployment."""

    def encrypt(self, data: str) -> str:
        """Encrypt a payload."""
        ...

    def decrypt(self, data: str) -> str:
        """Decrypt a payload inside the executor."""
        ...


@dataclass(frozen=True)
class RotationStatus:
    """Metadata safe for a receipt. No decrypted or encrypted credential."""

    rotation_id: str
    old_key_id: str
    new_key_id: str | None
    state: str
    revision: int


class RotationStore:
    """Commit state before side effects and fail closed on concurrent work."""

    def __init__(self, db: Session, cipher: Cipher) -> None:
        self.db = db
        self.cipher = cipher

    def _row(self) -> AWSKeyRotation:
        """Refresh durable state instead of trusting an ORM identity cache."""
        row = self.db.get(AWSKeyRotation, ACCOUNT, populate_existing=True)
        if row is None:
            raise RotationError("rotation_missing")
        return row

    def status(self) -> RotationStatus:
        """Return only metadata."""
        row = self._row()
        return RotationStatus(
            row.rotation_id, row.old_key_id, row.new_key_id, row.state, row.revision
        )

    def reserve(self) -> RotationStatus:
        """Persist an exclusive intent BEFORE AWS CreateAccessKey."""
        row = AWSKeyRotation(
            account_id=ACCOUNT,
            rotation_id=str(uuid.uuid4()),
            old_key_id=OLD_KEY,
            state="creating",
            revision=0,
        )
        try:
            self.db.add(row)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise RotationError("rotation_already_exists_or_storage_failed") from None
        return self.status()

    def transition(
        self, current: RotationStatus, state: str, **values
    ) -> RotationStatus:
        """Compare-and-swap the revision; never silently replay a side effect."""
        try:
            changed = (
                self.db.query(AWSKeyRotation)
                .filter(
                    AWSKeyRotation.account_id == ACCOUNT,
                    AWSKeyRotation.rotation_id == current.rotation_id,
                    AWSKeyRotation.state == current.state,
                    AWSKeyRotation.revision == current.revision,
                )
                .update(
                    {"state": state, "revision": current.revision + 1, **values},
                    synchronize_session=False,
                )
            )
            if changed != 1:
                raise RotationError("rotation_conflict")
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise RotationError("rotation_transition_failed") from None
        return self.status()

    def save(self, current: RotationStatus, key_id: str, secret: str) -> RotationStatus:
        """Bind ciphertext to alias, account, rotation and key identifiers."""
        if current.state != "creating" or not key_id or key_id == OLD_KEY or not secret:
            raise RotationError("rotation_credential_invalid")
        payload = json.dumps(
            {
                "alias": ALIAS,
                "account": ACCOUNT,
                "rotation_id": current.rotation_id,
                "key_id": key_id,
                "secret": secret,
            }
        )
        try:
            encrypted = self.cipher.encrypt(payload)
        except Exception:
            raise RotationError("rotation_encryption_failed") from None
        return self.transition(
            current, "stored", new_key_id=key_id, encrypted_credential=encrypted
        )

    def consume(self, current: RotationStatus, operation: Callable[[str, str], T]) -> T:
        """Inject material into a trusted internal adapter, never an API response."""
        row = self._row()
        if (row.rotation_id, row.revision) != (current.rotation_id, current.revision):
            raise RotationError("rotation_conflict")
        try:
            data = json.loads(self.cipher.decrypt(row.encrypted_credential))
            expected = (ALIAS, ACCOUNT, row.rotation_id, row.new_key_id)
            actual = tuple(
                data[k] for k in ("alias", "account", "rotation_id", "key_id")
            )
            if (
                actual != expected
                or not isinstance(data["secret"], str)
                or not data["secret"]
            ):
                raise ValueError()
            return operation(data["key_id"], data["secret"])
        except Exception:
            raise RotationError("rotation_injected_operation_failed") from None
