"""Create or upgrade a self-hosted SQLite database at startup.

The scripts live in ``backend/sqlite_migrations`` (PostgreSQL deployments run
``backend/migrations`` before the app starts). They cover the open-source
tables only; a plug-in's own tables are never part of them. A lock file beside
the database keeps several worker processes from upgrading it at once.
"""
import contextlib
from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

from app.db import Base

try:
    import fcntl
except ImportError:  # Windows: no lock; run one process.
    fcntl = None

SCRIPTS = Path(__file__).resolve().parent.parent / "sqlite_migrations"


def open_source_tables() -> set[str]:
    return {mapper.local_table.name for mapper in Base.registry.mappers if mapper.class_.__module__.startswith("app.")}


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    return type_ != "table" or name in open_source_tables()


def render_item(type_, obj, autogen_context):
    """JSONB columns are JSON on SQLite. A quoted 'false' default would be stored
    as text, which reads back as true; render the boolean instead."""
    if type_ == "type" and isinstance(obj, JSONB):
        return "sa.JSON()"
    if type_ == "server_default" and getattr(obj, "arg", None) in ("false", "true"):
        return f"sa.{obj.arg}()"
    return False


def compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    if isinstance(metadata_type, JSONB):
        return not isinstance(inspected_type, JSON)
    return None


# Alembic context options shared by the migration environment and the schema test.
MIGRATION_OPTIONS = {
    "render_as_batch": True,
    "include_object": include_object,
    "render_item": render_item,
    "compare_type": compare_type,
}


@contextlib.contextmanager
def _exclusive(database: str | None) -> Iterator[None]:
    if fcntl is None or not database or database == ":memory:":
        yield
        return
    with open(f"{database}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def upgrade_sqlite_schema(engine: Engine) -> None:
    config = Config()
    config.set_main_option("script_location", str(SCRIPTS))
    with _exclusive(engine.url.database), engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
