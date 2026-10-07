"""Dummy-only rotation tests: no AWS calls or production configuration."""

import json
from dataclasses import asdict
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models.aws_key_rotation import AWSKeyRotation
from app.services.aws_key_rotation import ACCOUNTS, CONSUMERS, Rotation
from app.services.aws_rotation_store import OLD_KEY, RotationError, RotationStore

SECRET = "dummy-only-secret-do-not-log"
NEW_KEY = "dummy-new-key"


class TestCipher:
    """Use an ephemeral test key, never the production EncryptionManager."""

    __test__ = False

    def __init__(self, key):
        self.fernet = Fernet(key)

    def encrypt(self, value):
        return self.fernet.encrypt(value.encode()).decode()

    def decrypt(self, value):
        return self.fernet.decrypt(value.encode()).decode()


@pytest.fixture
def rig(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rotation.sqlite'}", echo=False)
    AWSKeyRotation.__table__.create(engine)
    key = Fernet.generate_key()
    db = Session(engine)
    store = RotationStore(db, TestCipher(key))
    adapter = Mock()
    adapter.preflight.return_value = True
    adapter.create.return_value = (NEW_KEY, SECRET)
    adapter.verify.return_value = True
    yield Rotation(store, adapter, tmp_path / "rotation.lock"), adapter, engine, key
    db.close()
    engine.dispose()


def test_success_stores_only_ciphertext_and_checks_every_consumer(rig):
    rotation, adapter, engine, _ = rig
    receipt = rotation.prepare()
    assert receipt.state == "stored"
    assert SECRET not in json.dumps(asdict(receipt))
    with engine.connect() as db:
        cipher = db.execute(
            text("SELECT encrypted_credential FROM aws_key_rotations")
        ).scalar()
    assert SECRET not in cipher
    assert rotation.distribute().state == "verified"
    assert [call.args[0] for call in adapter.install.call_args_list] == list(CONSUMERS)
    assert rotation.retire().state == "old_inactive"
    assert adapter.verify.call_count == len(CONSUMERS) * len(ACCOUNTS) * 3
    adapter.set_old_active.assert_called_once_with(NEW_KEY, SECRET, False)


def test_durable_storage_survives_new_engine_and_cipher(rig):
    rotation, _, engine, key = rig
    receipt = rotation.prepare()
    other_engine = create_engine(engine.url)
    with Session(other_engine) as db:
        store = RotationStore(db, TestCipher(key))
        assert store.status() == receipt
        assert store.consume(receipt, lambda key_id, value: value == SECRET) is True
    other_engine.dispose()


def test_wrong_encryption_key_cannot_distribute(rig):
    rotation, adapter, _, _ = rig
    rotation.prepare()
    rotation.store.cipher = TestCipher(Fernet.generate_key())
    with pytest.raises(RotationError, match="rotation_distribution_failed"):
        rotation.distribute()
    adapter.install.assert_not_called()
    adapter.set_old_active.assert_not_called()


def test_ciphertext_is_bound_to_rotation_id(rig):
    rotation, adapter, engine, _ = rig
    rotation.prepare()
    with engine.begin() as db:
        db.execute(text("UPDATE aws_key_rotations SET rotation_id='other-rotation'"))
    with pytest.raises(RotationError, match="rotation_distribution_failed"):
        rotation.distribute()
    adapter.install.assert_not_called()


def test_preflight_failure_has_no_side_effects(rig):
    rotation, adapter, _, _ = rig
    adapter.preflight.return_value = False
    with pytest.raises(RotationError, match="rotation_preflight_failed"):
        rotation.prepare()
    adapter.create.assert_not_called()
    with pytest.raises(RotationError, match="rotation_missing"):
        rotation.store.status()


def test_lost_aws_response_cannot_create_another_key(rig):
    rotation, adapter, _, _ = rig
    adapter.create.side_effect = RuntimeError(SECRET)
    with pytest.raises(RotationError) as error:
        rotation.prepare()
    assert SECRET not in str(error.value)
    assert rotation.store.status().state == "creating"
    with pytest.raises(RotationError):
        rotation.prepare()
    assert adapter.create.call_count == 1
    adapter.set_old_active.assert_not_called()


def test_storage_failure_after_creation_never_disables_old_key(rig):
    rotation, adapter, _, _ = rig
    rotation.store.cipher.encrypt = Mock(side_effect=RuntimeError(SECRET))
    with pytest.raises(RotationError, match="rotation_prepare_requires_reconciliation"):
        rotation.prepare()
    assert rotation.store.status().state == "creating"
    adapter.install.assert_not_called()
    adapter.set_old_active.assert_not_called()


def test_partial_distribution_keeps_old_key_active_and_can_retry(rig):
    rotation, adapter, _, _ = rig
    rotation.prepare()
    adapter.install.side_effect = [None, RuntimeError(SECRET)]
    with pytest.raises(RotationError, match="rotation_distribution_failed"):
        rotation.distribute()
    assert rotation.store.status().state == "distribution_failed"
    adapter.set_old_active.assert_not_called()
    adapter.install.side_effect = None
    assert rotation.distribute().state == "verified"


def test_retirement_requires_distribution(rig):
    rotation, adapter, _, _ = rig
    rotation.prepare()
    with pytest.raises(RotationError, match="rotation_stage_not_allowed"):
        rotation.retire()
    adapter.set_old_active.assert_not_called()


def test_stale_success_does_not_allow_retirement(rig):
    rotation, adapter, _, _ = rig
    rotation.prepare()
    rotation.distribute()
    adapter.verify.return_value = False
    with pytest.raises(RotationError, match="rotation_retirement_precheck_failed"):
        rotation.retire()
    adapter.set_old_active.assert_not_called()


def test_post_disable_failure_reactivates_old_key(rig):
    rotation, adapter, _, _ = rig
    rotation.prepare()
    rotation.distribute()
    adapter.verify.side_effect = [True] * 9 + [False]
    with pytest.raises(RotationError, match="rotation_retirement_rolled_back"):
        rotation.retire()
    assert [c.args[-1] for c in adapter.set_old_active.call_args_list] == [False, True]
    assert rotation.store.status().state == "old_reactivated"


def test_failed_rollback_is_reported_as_recovery_required(rig):
    rotation, adapter, _, _ = rig
    rotation.prepare()
    rotation.distribute()
    adapter.set_old_active.side_effect = RuntimeError(SECRET)
    with pytest.raises(RotationError, match="rotation_recovery_required"):
        rotation.retire()
    assert rotation.store.status().state == "recovery_required"
    adapter.set_old_active.side_effect = None
    assert rotation.recover().state == "old_reactivated"


def test_stale_state_cannot_overwrite_newer_state(rig):
    rotation, _, _, _ = rig
    receipt = rotation.prepare()
    rotation.store.transition(receipt, "distributing")
    with pytest.raises(RotationError, match="rotation_transition_failed"):
        rotation.store.transition(receipt, "verified")
    assert rotation.store.status().state == "distributing"


def test_duplicate_reservation_cannot_create_second_key(rig):
    rotation, adapter, engine, key = rig
    rotation.prepare()
    with Session(engine) as db:
        other = Rotation(
            RotationStore(db, TestCipher(key)), adapter, rotation.lock_path
        )
        with pytest.raises(RotationError):
            other.prepare()
    assert adapter.create.call_count == 1


def test_old_key_cannot_be_used_as_replacement(rig):
    rotation, adapter, _, _ = rig
    adapter.create.return_value = (OLD_KEY, SECRET)
    with pytest.raises(RotationError, match="rotation_prepare_requires_reconciliation"):
        rotation.prepare()
    adapter.install.assert_not_called()


def test_recovery_cannot_race_an_active_operation(rig):
    from app.services.aws_rotation_lock import operation_lock

    rotation, adapter, _, _ = rig
    rotation.prepare()
    rotation.distribute()
    with operation_lock(rotation.lock_path):
        with pytest.raises(RotationError, match="rotation_busy_or_lock_invalid"):
            rotation.retire()
        with pytest.raises(RotationError, match="rotation_busy_or_lock_invalid"):
            rotation.recover()
    adapter.set_old_active.assert_not_called()


def test_lock_rejects_symlink_and_world_readable_file(rig, tmp_path):
    rotation, adapter, _, _ = rig
    target = tmp_path / "target"
    target.touch(mode=0o600)
    rotation.lock_path.symlink_to(target)
    with pytest.raises(RotationError, match="rotation_busy_or_lock_invalid"):
        rotation.prepare()
    rotation.lock_path.unlink()
    rotation.lock_path.touch(mode=0o644)
    with pytest.raises(RotationError, match="rotation_busy_or_lock_invalid"):
        rotation.prepare()
    adapter.create.assert_not_called()


def test_interrupted_distribution_can_resume_under_exclusive_lock(rig):
    rotation, _, _, _ = rig
    receipt = rotation.prepare()
    rotation.store.transition(receipt, "distributing")
    assert rotation.distribute().state == "verified"


def test_interrupted_retirement_can_reactivate_old_key(rig):
    rotation, adapter, _, _ = rig
    rotation.prepare()
    receipt = rotation.distribute()
    rotation.store.transition(receipt, "retiring")
    assert rotation.recover().state == "old_reactivated"
    adapter.set_old_active.assert_called_once_with(NEW_KEY, SECRET, True)


def test_migration_refuses_to_drop_recovery_material(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/f2a3b4c5d6e7_aws_key_rotations.py"
    )
    spec = importlib.util.spec_from_file_location("rotation_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    with engine.begin() as connection:
        monkeypatch.setattr(
            migration, "op", Operations(MigrationContext.configure(connection))
        )
        migration.upgrade()
        assert "aws_key_rotations" in inspect(connection).get_table_names()
        connection.execute(
            text(
                "INSERT INTO aws_key_rotations "
                "(account_id, rotation_id, old_key_id, state, revision) "
                "VALUES ('970651210182', 'dummy', 'dummy-old', 'creating', 0)"
            )
        )
        with pytest.raises(RuntimeError, match="Reconcile AWS rotations"):
            migration.downgrade()
        assert "aws_key_rotations" in inspect(connection).get_table_names()
    engine.dispose()
