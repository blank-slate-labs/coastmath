"""Secrets a self-hosted SQLite instance generates for itself.

When ``DATABASE_URL`` names an SQLite file and ``SESSION_SECRET`` or
``LEDGER_ENCRYPTION_KEY`` is unset, the first start writes random values to
``<database file>.secrets.json`` (mode 0600) and later starts read them back, so
restarts keep sessions signed in and stored provider credentials readable.
An environment value always wins; nothing is generated for other databases.
"""
import json
import os
import secrets
from pathlib import Path

from sqlalchemy.engine import make_url

GENERATED = ("SESSION_SECRET", "LEDGER_ENCRYPTION_KEY")


def secrets_file(database_url: str | None) -> Path | None:
    """The secrets file beside an SQLite database file, or None for any other database."""
    if not database_url:
        return None
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or url.database in (None, "", ":memory:"):
        return None
    return Path(f"{url.database}.secrets.json")


def _read(path: Path) -> dict[str, str]:
    values = json.loads(path.read_text())
    if not isinstance(values, dict) or any(not isinstance(values.get(name), str) for name in GENERATED):
        raise RuntimeError(f"{path} is not a valid secrets file.")
    return values


def _create(path: Path) -> dict[str, str]:
    """Write new values unless another process created the file first."""
    values = {name: secrets.token_urlsafe(48) for name in GENERATED}
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as file:
        json.dump(values, file)
    try:
        os.link(partial, path)  # Fails if the file exists: the first writer wins.
    except FileExistsError:
        return _read(path)
    finally:
        partial.unlink()
    return values


def load_instance_secrets(database_url: str | None) -> None:
    """Set each unset generated secret in the environment from the instance's secrets file."""
    path = secrets_file(database_url)
    missing = [name for name in GENERATED if not os.environ.get(name, "").strip()]
    if path is None or not missing:
        return
    values = _read(path) if path.exists() else _create(path)
    for name in missing:
        os.environ[name] = values[name]
