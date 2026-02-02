import os
import secrets
import hashlib
import hmac
import base64
from typing import Optional, Union

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

from src.common.config.settings import get_settings


def generate_encryption_key() -> bytes:
    return Fernet.generate_key()


def derive_key_from_password(
    password: str,
    salt: Optional[bytes] = None,
    iterations: int = 480000,
) -> tuple[bytes, bytes]:
    if salt is None:
        salt = os.urandom(16)
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
        backend=default_backend(),
    )
    
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    
    return key, salt


def get_fernet_instance(key: Optional[bytes] = None) -> Fernet:
    if key is None:
        settings = get_settings()
        if settings.encryption_key:
            key = settings.encryption_key.get_secret_value().encode()
        else:
            raise ValueError("No encryption key configured")
    
    if len(key) == 32:
        key = base64.urlsafe_b64encode(key)
    
    return Fernet(key)


def encrypt_data(
    data: Union[str, bytes],
    key: Optional[bytes] = None,
) -> bytes:
    if isinstance(data, str):
        data = data.encode("utf-8")
    
    fernet = get_fernet_instance(key)
    encrypted = fernet.encrypt(data)
    
    return encrypted


def decrypt_data(
    encrypted_data: bytes,
    key: Optional[bytes] = None,
) -> bytes:
    fernet = get_fernet_instance(key)
    
    try:
        decrypted = fernet.decrypt(encrypted_data)
        return decrypted
    except InvalidToken:
        raise ValueError("Invalid token or key - decryption failed")


def encrypt_string(
    plaintext: str,
    key: Optional[bytes] = None,
) -> str:
    encrypted_bytes = encrypt_data(plaintext, key)
    return base64.urlsafe_b64encode(encrypted_bytes).decode("utf-8")


def decrypt_string(
    ciphertext: str,
    key: Optional[bytes] = None,
) -> str:
    encrypted_bytes = base64.urlsafe_b64decode(ciphertext.encode("utf-8"))
    decrypted_bytes = decrypt_data(encrypted_bytes, key)
    return decrypted_bytes.decode("utf-8")


def hash_data(
    data: Union[str, bytes],
    algorithm: str = "sha256",
) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    
    hash_obj = hashlib.new(algorithm)
    hash_obj.update(data)
    
    return hash_obj.hexdigest()


def verify_hash(
    data: Union[str, bytes],
    expected_hash: str,
    algorithm: str = "sha256",
) -> bool:
    computed_hash = hash_data(data, algorithm)
    return secrets.compare_digest(computed_hash, expected_hash)


def hash_with_salt(
    data: Union[str, bytes],
    salt: Optional[bytes] = None,
    algorithm: str = "sha256",
) -> tuple[str, bytes]:
    if isinstance(data, str):
        data = data.encode("utf-8")
    
    if salt is None:
        salt = os.urandom(16)
    
    hash_obj = hashlib.new(algorithm)
    hash_obj.update(salt + data)
    
    return hash_obj.hexdigest(), salt


def verify_salted_hash(
    data: Union[str, bytes],
    expected_hash: str,
    salt: bytes,
    algorithm: str = "sha256",
) -> bool:
    computed_hash, _ = hash_with_salt(data, salt, algorithm)
    return secrets.compare_digest(computed_hash, expected_hash)


def generate_signature(
    data: Union[str, bytes],
    secret: Union[str, bytes],
    algorithm: str = "sha256",
) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    
    signature = hmac.new(secret, data, algorithm).hexdigest()
    
    return signature


def verify_signature(
    data: Union[str, bytes],
    signature: str,
    secret: Union[str, bytes],
    algorithm: str = "sha256",
) -> bool:
    expected_signature = generate_signature(data, secret, algorithm)
    return secrets.compare_digest(signature, expected_signature)


def generate_secure_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def generate_hex_token(length: int = 32) -> str:
    return secrets.token_hex(length)


class EncryptedField:
    def __init__(self, key: Optional[bytes] = None):
        self._key = key
    
    def encrypt(self, value: str) -> str:
        return encrypt_string(value, self._key)
    
    def decrypt(self, encrypted_value: str) -> str:
        return decrypt_string(encrypted_value, self._key)


class DataMasker:
    MASK_CHAR = "*"
    
    @classmethod
    def mask_email(cls, email: str) -> str:
        if "@" not in email:
            return cls.mask_string(email)
        local, domain = email.rsplit("@", 1)
        if len(local) <= 2:
            masked_local = cls.MASK_CHAR * len(local)
        else:
            masked_local = local[0] + cls.MASK_CHAR * (len(local) - 2) + local[-1]
        return f"{masked_local}@{domain}"
    
    @classmethod
    def mask_string(cls, value: str, visible_chars: int = 4) -> str:
        if len(value) <= visible_chars:
            return cls.MASK_CHAR * len(value)
        return value[:visible_chars] + cls.MASK_CHAR * (len(value) - visible_chars)
    
    @classmethod
    def mask_api_key(cls, api_key: str) -> str:
        if "_" in api_key:
            prefix, key = api_key.split("_", 1)
            return f"{prefix}_{cls.MASK_CHAR * (len(key) - 4)}{key[-4:]}"
        return cls.mask_string(api_key, 4)
    
    @classmethod
    def mask_token(cls, token: str) -> str:
        if len(token) <= 8:
            return cls.MASK_CHAR * len(token)
        return token[:4] + cls.MASK_CHAR * (len(token) - 8) + token[-4:]


def redact_sensitive_data(
    data: dict,
    sensitive_keys: Optional[set[str]] = None,
) -> dict:
    if sensitive_keys is None:
        sensitive_keys = {
            "password", "secret", "token", "key", "api_key",
            "access_token", "refresh_token", "authorization",
            "credential", "private_key", "ssh_key",
        }
    
    redacted = {}
    for key, value in data.items():
        key_lower = key.lower()
        if any(sk in key_lower for sk in sensitive_keys):
            redacted[key] = "[REDACTED]"
        elif isinstance(value, dict):
            redacted[key] = redact_sensitive_data(value, sensitive_keys)
        elif isinstance(value, list):
            redacted[key] = [
                redact_sensitive_data(item, sensitive_keys)
                if isinstance(item, dict) else item
                for item in value
            ]
        else:
            redacted[key] = value
    
    return redacted
