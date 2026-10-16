"""Run the PostgreSQL models on SQLite: self-hosted instances and the test suite.

The models use PostgreSQL types and server defaults. On SQLite:

- JSONB columns are stored as JSON.
- Timezone-aware ``DateTime`` columns are stored in UTC and read back as UTC,
  as PostgreSQL returns them, instead of as naive values.
- ``id``, ``created_at`` and empty-dict JSON columns get Python-side values
  before a flush, because ``gen_random_uuid()`` and ``now()`` don't exist there.
- Foreign keys are enforced, so account and plan deletion cascade.
- A new database file is created readable by the server's user only.
"""
import contextlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.dialects import sqlite
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import DateTime


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


class _UTCDateTime(sqlite.DATETIME):
    """SQLite text timestamps; timezone-aware columns convert to and from UTC."""

    def bind_processor(self, dialect):
        process = super().bind_processor(dialect)
        if not self.timezone:
            return process

        def convert(value):
            if value is not None and value.tzinfo is not None:
                value = value.astimezone(UTC)
            return process(value) if process else value
        return convert

    def result_processor(self, dialect, coltype):
        process = super().result_processor(dialect, coltype)
        if not self.timezone:
            return process

        def convert(value):
            value = process(value) if process else value
            return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value
        return convert


def is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite:")


def configure_sqlite_engine(engine: Engine) -> Engine:
    """Apply the dialect adjustments and connection settings to an SQLite engine."""
    engine.dialect.colspecs = {**engine.dialect.colspecs, DateTime: _UTCDateTime}
    event.listen(engine, "connect", _configure_connection)
    return engine


def database_file(url: str) -> Path | None:
    """The file an SQLite URL names, or None for an in-memory or URI database."""
    database = make_url(url).database
    if not database or database == ":memory:" or database.startswith("file:"):
        return None
    return Path(database)


def create_database_file(path: Path) -> None:
    """Create an empty database file that only its owner can read.

    SQLite would create it with the process umask (world-readable by default),
    and it holds every plan and the encrypted bank credentials. SQLite gives the
    ``-wal`` and ``-shm`` files the database file's mode. An existing file keeps
    its mode; a missing parent directory is left for SQLite to report.
    """
    if path.exists() or not path.parent.is_dir():
        return
    with contextlib.suppress(FileExistsError):
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))


def create_sqlite_engine(url: str, **kwargs) -> Engine:
    path = database_file(url)
    if path is not None:
        create_database_file(path)
    connect_args = {"check_same_thread": False, "timeout": 30, **kwargs.pop("connect_args", {})}
    return configure_sqlite_engine(create_engine(url, connect_args=connect_args, **kwargs))


def _configure_connection(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    # Lets readers continue while the background workers write (a file database only).
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def install_python_defaults(session_factory) -> None:
    """Fill the values PostgreSQL server defaults would supply for new rows."""
    event.listen(session_factory, "before_flush", _set_python_defaults)


def _set_python_defaults(session, _flush_context, _instances) -> None:
    for obj in session.new:
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        if hasattr(obj, "created_at") and obj.created_at is None:
            obj.created_at = datetime.now(UTC)
        if hasattr(obj, "settings") and obj.settings is None:
            obj.settings = {}
        if hasattr(obj, "snapshot_conditions") and obj.snapshot_conditions is None:
            obj.snapshot_conditions = {}
