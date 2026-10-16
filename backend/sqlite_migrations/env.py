"""Alembic environment for self-hosted SQLite databases (see sqlite_alembic.ini).

The app runs these at startup (app.sqlite_schema). Batch mode rebuilds tables
for changes SQLite can't ALTER.
"""
import os
from logging.config import fileConfig

from alembic import context

import app.models  # noqa: F401 — registers every open-source table
from app.db import Base
from app.sqlite_schema import MIGRATION_OPTIONS
from app.sqlite_support import create_sqlite_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run(connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, **MIGRATION_OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("SQLite migrations run online only.")
if (connection := config.attributes.get("connection")) is not None:
    run(connection)
else:
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_URL", "")
    if not url.startswith("sqlite:"):
        raise RuntimeError("Set DATABASE_URL to an sqlite:/// URL.")
    with create_sqlite_engine(url).connect() as connection:
        run(connection)
