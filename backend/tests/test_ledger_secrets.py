"""Per-connection credential encryption: keys, rotation and typed failures."""
import pytest

from app.auth.config import DEV_SESSION_SECRET
from app.ledger import secrets
from app.ledger.secrets import CredentialError, EncryptionUnavailable

KEY = "synthetic-ledger-key-0123456789-abcdef"
OLD = "synthetic-old-ledger-key-0123456789-xyz"
SESSION = "synthetic-session-secret-0123456789-abc"
PLAIN = "https://user:pass@bridge.example/simplefin"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("LEDGER_ENCRYPTION_KEY", "LEDGER_ENCRYPTION_KEYS_PREVIOUS", "SESSION_SECRET"):
        monkeypatch.delenv(name, raising=False)


def test_round_trip_with_configured_key(monkeypatch):
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", KEY)
    ciphertext = secrets.encrypt(PLAIN)
    assert ciphertext.startswith("v1:") and PLAIN not in ciphertext
    assert secrets.decrypt(ciphertext) == PLAIN
    assert secrets.available()


def test_session_secret_fallback_is_domain_separated(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", SESSION)
    ciphertext = secrets.encrypt(PLAIN)
    assert secrets.decrypt(ciphertext) == PLAIN
    # A configured key replaces the derived one; the old ciphertext no longer reads.
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", KEY)
    with pytest.raises(CredentialError):
        secrets.decrypt(ciphertext)
    # Unless the session secret is listed as a previous key.
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEYS_PREVIOUS", f" , {SESSION}")
    assert secrets.decrypt(ciphertext) == PLAIN


@pytest.mark.parametrize("session", [None, DEV_SESSION_SECRET, "short"])
def test_weak_or_missing_secret_is_refused(monkeypatch, session):
    if session:
        monkeypatch.setenv("SESSION_SECRET", session)
    assert not secrets.available()
    with pytest.raises(EncryptionUnavailable) as error:
        secrets.encrypt(PLAIN)
    assert error.value.code == "INTEGRATION_UNAVAILABLE"
    # Decryption without a key is a reconnect state, never a crash.
    with pytest.raises(CredentialError):
        secrets.decrypt("v1:anything")


def test_short_configured_key_is_refused(monkeypatch):
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", "too-short")
    monkeypatch.setenv("SESSION_SECRET", SESSION)
    with pytest.raises(EncryptionUnavailable, match="32 characters"):
        secrets.encrypt(PLAIN)


def test_rotation(monkeypatch):
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", OLD)
    old = secrets.encrypt(PLAIN)
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", KEY)
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEYS_PREVIOUS", f"{OLD},{KEY}")
    assert secrets.decrypt(old) == PLAIN
    fresh = secrets.rotated(old)
    assert fresh and fresh != old and secrets.decrypt(fresh) == PLAIN
    assert secrets.rotated(fresh) is None
    monkeypatch.delenv("LEDGER_ENCRYPTION_KEYS_PREVIOUS")
    assert secrets.decrypt(fresh) == PLAIN
    with pytest.raises(CredentialError):
        secrets.rotated(old)


@pytest.mark.parametrize("value", [None, "", "plain-text", "v2:abc", "v1:not-a-token", "v1:é"])
def test_unreadable_ciphertexts_are_typed(monkeypatch, value):
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", KEY)
    with pytest.raises(CredentialError) as error:
        secrets.decrypt(value)
    assert error.value.code == "CREDENTIAL_UNREADABLE"
    assert "Reconnect" in error.value.message


def test_wrong_key_and_tampering(monkeypatch):
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", KEY)
    ciphertext = secrets.encrypt(PLAIN)
    tampered = ciphertext[:-4] + ("AAAA" if not ciphertext.endswith("AAAA") else "BBBB")
    with pytest.raises(CredentialError):
        secrets.decrypt(tampered)
    monkeypatch.setenv("LEDGER_ENCRYPTION_KEY", OLD)
    with pytest.raises(CredentialError):
        secrets.decrypt(ciphertext)
