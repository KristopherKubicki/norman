import importlib
import sys
import types

import pytest

from app.core.test_settings import TestSettings


def load_encryption_module(monkeypatch):
    class DummyFernet:
        def __init__(self, key):
            self.key = key

        def encrypt(self, data: bytes) -> bytes:
            return b"ENC:" + data

        def decrypt(self, token: bytes) -> bytes:
            assert token.startswith(b"ENC:")
            return token[4:]

    class DummyKDF:
        def __init__(self, *args, **kwargs):
            pass

        def derive(self, key: bytes) -> bytes:
            return key

    hashes_mod = types.ModuleType("hashes")

    class SHA256:
        def __init__(self):
            pass

    hashes_mod.SHA256 = SHA256

    backend_mod = types.ModuleType("backends")
    backend_mod.default_backend = lambda: None

    monkeypatch.setitem(sys.modules, "cryptography", types.ModuleType("cryptography"))
    monkeypatch.setitem(sys.modules, "cryptography.fernet", types.SimpleNamespace(Fernet=DummyFernet))
    hazmat_mod = types.ModuleType("hazmat")
    monkeypatch.setitem(sys.modules, "cryptography.hazmat", hazmat_mod)
    primitives_mod = types.ModuleType("primitives")
    kdf_mod = types.ModuleType("kdf")
    pbkdf2_mod = types.SimpleNamespace(PBKDF2HMAC=DummyKDF)
    kdf_mod.pbkdf2 = pbkdf2_mod
    primitives_mod.hashes = hashes_mod
    primitives_mod.kdf = kdf_mod
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives", primitives_mod)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.hashes", hashes_mod)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.kdf", kdf_mod)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.kdf.pbkdf2", pbkdf2_mod)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.backends", backend_mod)

    if "app.core.encryption" in sys.modules:
        del sys.modules["app.core.encryption"]
    return importlib.import_module("app.core.encryption")


def test_encrypt_decrypt_round_trip(monkeypatch):
    enc = load_encryption_module(monkeypatch)
    monkeypatch.setattr(enc, "get_settings", lambda: TestSettings)
    manager = enc.EncryptionManager()
    plaintext = "secret message"
    encrypted = manager.encrypt(plaintext)
    assert encrypted != plaintext
    assert manager.decrypt(encrypted) == plaintext


@pytest.mark.parametrize(
    "key,salt",
    [
        (None, "salt"),
        ("key", None),
        (None, None),
    ],
)
def test_missing_config_raises_value_error(monkeypatch, key, salt):
    enc = load_encryption_module(monkeypatch)

    class DummySettings:
        encryption_key = key
        encryption_salt = salt

    monkeypatch.setattr(enc, "get_settings", lambda: DummySettings)
    with pytest.raises(ValueError):
        enc.EncryptionManager()
