"""A self-hosted instance on an SQLite file: schema migrations, generated
secrets, cookies and the full request path in a separate server process."""
import contextlib
import os
import socket
import sqlite3
import stat
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    Table,
    insert,
    inspect,
    select,
)

from app.auth import router
from app.db import Base
from app.instance_secrets import GENERATED, _create, load_instance_secrets, secrets_file
from app.sqlite_schema import (
    MIGRATION_OPTIONS,
    open_source_tables,
    upgrade_sqlite_schema,
)
from app.sqlite_support import create_sqlite_engine

BACKEND = Path(__file__).resolve().parent.parent


def test_migrations_build_exactly_the_open_source_models(tmp_path):
    engine = create_sqlite_engine(f"sqlite:///{tmp_path / 'coastmath.db'}")
    upgrade_sqlite_schema(engine)
    upgrade_sqlite_schema(engine)  # Already at head: a restart changes nothing.
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts=MIGRATION_OPTIONS)
        differences = compare_metadata(context, Base.metadata)
        tables = set(inspect(connection).get_table_names())
    # A model change needs an SQLite migration too (backend/sqlite_alembic.ini).
    assert differences == []
    assert tables == open_source_tables() | {"alembic_version"}


def test_new_database_file_is_private_to_its_owner(tmp_path):
    database = tmp_path / "coastmath.db"
    engine = create_sqlite_engine(f"sqlite:///{database}")
    table = Table("rows", MetaData(), Column("id", Integer, primary_key=True))
    with engine.begin() as connection:
        table.metadata.create_all(connection)
        connection.execute(insert(table).values(id=1))
        assert stat.S_IMODE(database.stat().st_mode) == 0o600
        # WAL mode: SQLite copies the database file's mode onto its journal files.
        assert stat.S_IMODE((tmp_path / "coastmath.db-wal").stat().st_mode) == 0o600
    engine.dispose()
    assert stat.S_IMODE(database.stat().st_mode) == 0o600


def test_existing_database_file_keeps_its_mode(tmp_path):
    database = tmp_path / "coastmath.db"
    database.touch(mode=0o644)
    os.chmod(database, 0o644)
    engine = create_sqlite_engine(f"sqlite:///{database}")
    with engine.connect() as connection:
        connection.execute(select(1))
    engine.dispose()
    assert stat.S_IMODE(database.stat().st_mode) == 0o644


def test_memory_and_uri_databases_create_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_sqlite_engine("sqlite://").dispose()
    create_sqlite_engine("sqlite:///:memory:").dispose()
    assert list(tmp_path.iterdir()) == []


def test_aware_timestamps_round_trip_as_utc():
    engine = create_sqlite_engine("sqlite://")
    table = Table("stamps", MetaData(), Column("id", Integer, primary_key=True), Column("at", DateTime(timezone=True)))
    table.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(table).values(id=1, at=datetime(2026, 1, 1, 7, tzinfo=timezone(timedelta(hours=-5)))))
        assert connection.execute(select(table.c.at)).scalar() == datetime(2026, 1, 1, 12, tzinfo=UTC)


@pytest.fixture
def no_secrets(monkeypatch):
    # Empty counts as unset; monkeypatch restores the real values afterwards.
    for name in GENERATED:
        monkeypatch.setenv(name, "")


def _secrets() -> dict[str, str]:
    return {name: os.environ[name] for name in GENERATED}


def test_an_sqlite_instance_generates_its_secrets_once(tmp_path, no_secrets):
    url = f"sqlite:///{tmp_path / 'coastmath.db'}"
    load_instance_secrets(url)
    first = _secrets()
    assert all(len(value) >= 32 for value in first.values()) and len(set(first.values())) == len(GENERATED)
    path = secrets_file(url)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [path]
    for name in GENERATED:
        os.environ[name] = ""
    load_instance_secrets(url)
    assert _secrets() == first


def test_configured_values_win_and_other_databases_generate_nothing(tmp_path, no_secrets):
    for url in (None, "postgresql://db.invalid/coastmath", "sqlite://", "sqlite:///:memory:"):
        load_instance_secrets(url)
        assert _secrets() == dict.fromkeys(GENERATED, "")
    assert list(tmp_path.iterdir()) == []
    os.environ["SESSION_SECRET"] = "configured-session-secret-of-at-least-32-chars"
    load_instance_secrets(f"sqlite:///{tmp_path / 'coastmath.db'}")
    assert os.environ["SESSION_SECRET"] == "configured-session-secret-of-at-least-32-chars"
    assert len(os.environ["LEDGER_ENCRYPTION_KEY"]) >= 32


def test_a_second_process_keeps_the_first_writers_secrets(tmp_path):
    path = tmp_path / "coastmath.db.secrets.json"
    first = _create(path)
    assert _create(path) == first
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.anyio
async def test_cookies_can_be_served_over_plain_http(client, monkeypatch):
    monkeypatch.setattr(router, "SESSION_SECRET", "configured-session-secret-of-at-least-32-chars")
    client.cookies.clear()
    assert "secure" in (await client.post("/api/auth/session")).headers["set-cookie"].lower()
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    client.cookies.clear()
    assert "secure" not in (await client.post("/api/auth/session")).headers["set-cookie"].lower()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@contextlib.contextmanager
def _server(database: Path):
    """The open-source app (no plug-ins) in its own process, as `uvicorn` runs it."""
    port = _free_port()
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}", "COASTMATH_PLUGINS": "",
           # Empty, so a developer's backend/.env cannot supply them either.
           **dict.fromkeys(GENERATED, "")}
    log = database.with_name(f"server_{port}.log")
    with open(log, "w") as output:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
                                   cwd=BACKEND, env=env, stdout=output, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 60
        while True:
            with contextlib.suppress(httpx.TransportError):
                if httpx.get(f"{base}/api/ready").status_code == 200:
                    break
            if process.poll() is not None or time.monotonic() > deadline:
                pytest.fail(f"server did not start:\n{log.read_text()}")
            time.sleep(0.2)
        yield base
    finally:
        process.terminate()
        process.wait(timeout=20)


def test_a_self_hosted_instance_serves_plans_across_restarts_and_deletes_by_cascade(tmp_path):
    database = tmp_path / "coastmath.db"
    with _server(database) as base:
        session = httpx.post(f"{base}/api/auth/session")
        assert session.status_code == 201
        cookie = session.headers["set-cookie"].split(";")[0].split("=", 1)[1]
        client = httpx.Client(base_url=base, cookies={"session": cookie}, timeout=60)
        plan = client.post("/api/plans", json={"name": "Self-hosted", "birth_year": 1980,
                                                 "retirement_milestone_age": 60})
        assert plan.status_code == 201
        projection = client.post(f"/api/plans/{plan.json()['id']}/simulate")
        assert projection.status_code == 200 and projection.json()["yearly_snapshots"]
    assert stat.S_IMODE(secrets_file(f"sqlite:///{database}").stat().st_mode) == 0o600
    with contextlib.closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT count(*) FROM milestones").fetchone() == (1,)
    # A restart keeps the schema, the data and the signing key.
    with _server(database) as base:
        client = httpx.Client(base_url=base, cookies={"session": cookie}, timeout=60)
        assert [row["name"] for row in client.get("/api/plans").json()] == ["Self-hosted"]
        deleted = client.request("DELETE", "/api/auth/me", json={"confirmation": "DELETE"})
        assert deleted.status_code == 204
    with contextlib.closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT count(*) FROM users").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM plans").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM milestones").fetchone() == (0,)
