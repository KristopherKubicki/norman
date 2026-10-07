"""Rotation binding validates requests before adapters or SDK calls."""

from unittest.mock import Mock
import pytest
from app.services import aws_rotation_executor as executor
from app.services.aws_rotation_store import ACCOUNT, RotationError


@pytest.mark.parametrize(
    "override",
    [
        {"executor_ref": "083762351172"},
        {"action": "delete"},
        {"parameters": {"account_id": ACCOUNT, "command": "anything"}},
        {"parameters": {"account_id": "703671901350"}},
    ],
)
def test_unbound_requests_never_execute(monkeypatch, override):
    run = Mock()
    monkeypatch.setattr(executor, "_execute", run)
    monkeypatch.setenv("NORMAN_KEYS_AWS_ROTATION_ENABLED", "1")
    args = {
        "executor_ref": ACCOUNT,
        "action": "prepare",
        "parameters": {"account_id": ACCOUNT},
    }
    with pytest.raises(RotationError):
        executor.execute_rotation(Mock(), **(args | override))
    run.assert_not_called()


def test_default_disabled(monkeypatch):
    monkeypatch.delenv("NORMAN_KEYS_AWS_ROTATION_ENABLED", raising=False)
    with pytest.raises(RotationError, match="rotation_disabled"):
        executor.execute_rotation(
            Mock(),
            executor_ref=ACCOUNT,
            action="prepare",
            parameters={"account_id": ACCOUNT},
        )


def test_unexpected_error_is_sanitized(monkeypatch):
    monkeypatch.setenv("NORMAN_KEYS_AWS_ROTATION_ENABLED", "1")
    monkeypatch.setattr(
        executor, "_execute", Mock(side_effect=RuntimeError("dummy-secret"))
    )
    with pytest.raises(RotationError) as error:
        executor.execute_rotation(
            Mock(),
            executor_ref=ACCOUNT,
            action="prepare",
            parameters={"account_id": ACCOUNT},
        )
    assert "dummy-secret" not in str(error.value)


def test_cipher_probe_survives_new_cipher_instance(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    from tests.test_aws_key_rotation import TestCipher

    monkeypatch.setattr(executor, "LOCK", tmp_path / "lock")
    monkeypatch.setattr(executor, "PROBE", tmp_path / "probe")
    key = Fernet.generate_key()
    assert executor.cipher_test(TestCipher(key)) == "cipher_initialized"
    assert executor.cipher_test(TestCipher(key)) == "cipher_verified"
    with pytest.raises(Exception):
        executor.cipher_test(TestCipher(Fernet.generate_key()))
