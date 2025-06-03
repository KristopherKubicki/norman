import pytest

pytest.importorskip("hypothesis")
from hypothesis import given, strategies as st, settings, HealthCheck

from app.core.test_settings import test_settings
from tests.test_encryption import load_encryption_module


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.text())
def test_encrypt_decrypt_round_trip_fuzz(monkeypatch, text: str) -> None:
    enc = load_encryption_module(monkeypatch)
    monkeypatch.setattr(enc, "get_settings", lambda: test_settings)
    manager = enc.EncryptionManager()
    encrypted = manager.encrypt(text)
    assert manager.decrypt(encrypted) == text
