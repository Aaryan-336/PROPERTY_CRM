"""At-rest encryption for third-party tokens.

MultiFernet so the key can be rotated: put the new key first, keep the old one
after it until every row has been re-encrypted by a reconnect.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import settings


class TokenCryptoUnavailable(RuntimeError):
    pass


def _fernet() -> MultiFernet:
    keys = [k.strip() for k in settings.meta_token_encryption_key.split(",") if k.strip()]
    if not keys:
        raise TokenCryptoUnavailable("META_TOKEN_ENCRYPTION_KEY is not set.")
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str | None:
    """None when the key no longer opens it -- treated as reconnect-required."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return None
