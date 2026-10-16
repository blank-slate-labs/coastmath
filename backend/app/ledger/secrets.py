"""Encryption at rest for per-connection provider credentials.

A SimpleFIN access URL or a Plaid access token is the customer's long-lived
credential. It is stored Fernet-encrypted in ``financial_connections.
credentials_encrypted`` and decrypted only for a provider call.

Keys
- ``LEDGER_ENCRYPTION_KEY``: any high-entropy string of at least 32
  characters. The Fernet key is derived from it with a ledger-specific domain
  label, so the same value never doubles as another subsystem's key.
- Without it, the key is derived from ``SESSION_SECRET`` with the same label
  (separate from any other derivation from it). The development default
  secret is refused.
- ``LEDGER_ENCRYPTION_KEYS_PREVIOUS``: comma-separated earlier values. Old
  ciphertexts still decrypt after a key change, and ``rotated`` re-encrypts
  them under the current key.

Ciphertexts carry a format prefix (``v1:``). Errors never include the
credential, the ciphertext or a key.
"""
import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.auth.config import DEV_SESSION_SECRET

VERSION = "v1"
_PREFIX = VERSION + ":"
_DOMAIN = "coastmath-ledger-credentials:v1:"
MIN_SECRET_LENGTH = 32


class CredentialError(Exception):
    """A stored credential cannot be decrypted; the connection needs reconnecting."""

    code = "CREDENTIAL_UNREADABLE"

    def __init__(self, message: str = "Saved provider access can no longer be read. Reconnect to continue."):
        super().__init__(message)
        self.message = message


class EncryptionUnavailable(Exception):
    """The server has no usable key; provider connections cannot be saved."""

    code = "INTEGRATION_UNAVAILABLE"

    def __init__(self, message: str = "Provider connections need an encryption key on this server."):
        super().__init__(message)
        self.message = message


def _fernet(secret: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256((_DOMAIN + secret).encode()).digest()))


def _current_secret() -> str:
    configured = os.getenv("LEDGER_ENCRYPTION_KEY", "").strip()
    if configured:
        if len(configured) < MIN_SECRET_LENGTH:
            raise EncryptionUnavailable("LEDGER_ENCRYPTION_KEY must contain at least 32 characters.")
        return configured
    session = os.getenv("SESSION_SECRET", "").strip()
    if not session or session == DEV_SESSION_SECRET or len(session) < MIN_SECRET_LENGTH:
        raise EncryptionUnavailable()
    return session


def _previous_secrets() -> list[str]:
    raw = os.getenv("LEDGER_ENCRYPTION_KEYS_PREVIOUS", "")
    return [value.strip() for value in raw.split(",") if value.strip()]


def _keys() -> MultiFernet:
    current = _current_secret()
    return MultiFernet([_fernet(current), *(_fernet(value) for value in _previous_secrets() if value != current)])


def available() -> bool:
    try:
        _current_secret()
    except EncryptionUnavailable:
        return False
    return True


def encrypt(plaintext: str) -> str:
    return _PREFIX + _keys().encrypt(plaintext.encode("utf-8")).decode("ascii")


def _token(ciphertext: str | None) -> bytes:
    if not ciphertext or not ciphertext.startswith(_PREFIX):
        raise CredentialError()
    return ciphertext[len(_PREFIX):].encode("ascii", "replace")


def decrypt(ciphertext: str | None) -> str:
    """The plaintext, or ``CredentialError`` (missing, foreign format or unknown key)."""
    token = _token(ciphertext)
    try:
        keys = _keys()
    except EncryptionUnavailable:
        raise CredentialError() from None
    try:
        return keys.decrypt(token).decode("utf-8")
    except (InvalidToken, UnicodeError):
        raise CredentialError() from None


def rotated(ciphertext: str) -> str | None:
    """A re-encryption under the current key when an earlier key wrote it; else None."""
    token = _token(ciphertext)
    current = _fernet(_current_secret())
    try:
        current.decrypt(token)
        return None
    except InvalidToken:
        pass
    try:
        return _PREFIX + _keys().rotate(token).decode("ascii")
    except InvalidToken:
        raise CredentialError() from None
