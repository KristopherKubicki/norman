from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from base64 import urlsafe_b64encode, urlsafe_b64decode
from app.core.config import get_settings


class EncryptionManager:
    def __init__(self):
        settings = get_settings()
        key = settings.encryption_key
        salt = settings.encryption_salt
        if key is None or salt is None:
            raise ValueError("No encryption key or salt provided in config.")
        self.key = key.encode()
        self.salt = salt.encode()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.salt,
            iterations=100000,
            backend=default_backend(),
        )
        self.fernet_key = urlsafe_b64encode(kdf.derive(self.key))
        self.fernet = Fernet(self.fernet_key)

    def encrypt(self, data: str) -> str:
        """Encrypt a plaintext string.

        Args:
            data: The plaintext value to encrypt.

        Returns:
            The encrypted text encoded as a UTF-8 string.
        """

        data_bytes = data.encode()
        encrypted = self.fernet.encrypt(data_bytes)
        return encrypted.decode()

    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt an encrypted string.

        Args:
            encrypted_data: The encrypted text to decrypt.

        Returns:
            The original plaintext string.
        """

        encrypted_bytes = encrypted_data.encode()
        decrypted = self.fernet.decrypt(encrypted_bytes)
        return decrypted.decode()
