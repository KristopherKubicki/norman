"""Fail-closed rotation workflow, not registered as a live capability.

Adapters must perform fixed, authenticated server-side operations. Until those
adapters and host distribution are reviewed and deployed, this runs only in tests.
No arbitrary commands, caller-chosen accounts, raw key APIs or key deletion.
"""

from __future__ import annotations

from typing import Protocol
from pathlib import Path

from app.services.aws_rotation_lock import exclusive

from app.services.aws_rotation_store import (
    ACCOUNT,
    OLD_KEY,
    RotationError,
    RotationStatus,
    RotationStore,
)

CONSUMERS = ("hal:kristopher", "norman:kristopher", "netops:root")
ACCOUNTS = (ACCOUNT, "104637383649", "703671901350")


class RotationAdapter(Protocol):
    """Trusted runtime boundary; implementations must never log secret material."""

    def preflight(self) -> bool:
        """Verify exact source principal/key, single active key and all receivers."""
        ...

    def create(self) -> tuple[str, str]:
        """Create one key for the fixed cloudagent user, never print its response."""
        ...

    def install(self, consumer: str, key_id: str, secret: str) -> None:
        """Atomically update both profiles and refresh cached clients."""
        ...

    def verify(self, consumer: str, account: str, key_id: str) -> bool:
        """Verify fresh source credentials, uncached identity and service health."""
        ...

    def set_old_active(self, key_id: str, secret: str, active: bool) -> None:
        """Use replacement auth to set OLD_KEY status and read it back."""
        ...


class Rotation:
    """Persist every unsafe interval and require fresh checks before retirement."""

    def __init__(
        self, store: RotationStore, adapter: RotationAdapter, lock_path: Path
    ) -> None:
        self.store = store
        self.adapter = adapter
        self.lock_path = lock_path

    @exclusive
    def prepare(self) -> RotationStatus:
        """Persist intent and encrypted key; uncertainty leaves old access intact."""
        try:
            if self.adapter.preflight() is not True:
                raise RotationError("rotation_preflight_failed")
        except Exception:
            raise RotationError("rotation_preflight_failed") from None
        current = self.store.reserve()
        try:
            key_id, secret = self.adapter.create()
            stored = self.store.save(current, key_id, secret)
            self.store.consume(stored, lambda candidate, _: candidate == key_id)
            return stored
        except Exception:
            # Never retry CreateAccessKey or disable/delete either key here.
            # A network timeout may mean AWS succeeded without returning a key.
            raise RotationError("rotation_prepare_requires_reconciliation") from None

    def _start(self, allowed: tuple[str, ...], next_state: str) -> RotationStatus:
        """Claim a stage atomically before attempting external changes."""
        current = self.store.status()
        if current.state not in allowed:
            raise RotationError("rotation_stage_not_allowed")
        return self.store.transition(current, next_state)

    @exclusive
    def distribute(self) -> RotationStatus:
        """Allow idempotent distribution retry; old key remains active throughout."""
        current = self._start(
            ("stored", "distribution_failed", "distributing"), "distributing"
        )
        try:
            for consumer in CONSUMERS:
                self.store.consume(
                    current,
                    lambda key, secret: self.adapter.install(consumer, key, secret),
                )
            self._verify(current)
        except Exception:
            self.store.transition(current, "distribution_failed")
            raise RotationError("rotation_distribution_failed") from None
        return self.store.transition(current, "verified")

    def _verify(self, current: RotationStatus) -> None:
        """A previous successful receipt or cached STS token is insufficient."""
        if not current.new_key_id or current.new_key_id == OLD_KEY:
            raise RotationError("rotation_new_key_missing")
        for consumer in CONSUMERS:
            for account in ACCOUNTS:
                if (
                    self.adapter.verify(consumer, account, current.new_key_id)
                    is not True
                ):
                    raise RotationError("rotation_consumer_check_failed")

    @exclusive
    def retire(self) -> RotationStatus:
        """Recheck every consumer before disabling, then check again afterward."""
        current = self._start(("verified",), "retiring")
        try:
            self._verify(current)
        except Exception:
            self.store.transition(current, "distribution_failed")
            raise RotationError("rotation_retirement_precheck_failed") from None
        try:
            self.store.consume(
                current,
                lambda key, secret: self.adapter.set_old_active(key, secret, False),
            )
            self._verify(current)
        except Exception:
            self._restore_old(current)
            raise RotationError("rotation_retirement_rolled_back") from None
        return self.store.transition(current, "old_inactive")

    def _restore_old(self, current: RotationStatus) -> RotationStatus:
        """Restore old authorization; migrated clients may keep using the new key."""
        try:
            self.store.consume(
                current,
                lambda key, secret: self.adapter.set_old_active(key, secret, True),
            )
        except Exception:
            self.store.transition(current, "recovery_required")
            raise RotationError("rotation_recovery_required") from None
        return self.store.transition(current, "old_reactivated")

    @exclusive
    def recover(self) -> RotationStatus:
        """Explicit recovery after interrupted retirement or a failed health check."""
        current = self._start(
            ("retiring", "old_inactive", "recovery_required", "recovering"),
            "recovering",
        )
        return self._restore_old(current)
