"""Shared SQLite test fixtures.

Test servers outside pytest import `Base`, `TestSession`, `app` and `get_db`
from this module: `tests/e2e_server.py` and the iOS client's local test
server. Keep those names and the SQLite defaults stable.
"""
import importlib
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tests.engine_support import fixture_to_plan_data
from tests.fixtures import load_standard_plan
from tests.intl_fixture_pack import (
    fixture_pack,  # noqa: F401 - the test-only country pack fixture
)

# Plan-blob routes are test infrastructure; production omits them. Routers are
# chosen when app.main is imported, so this must precede the app imports.
os.environ["ENABLE_STATELESS_API"] = "true"

from app import client_slots  # noqa: E402
from app.auth.router import create_jwt  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User  # noqa: E402
from app.plugins import extensions  # noqa: E402
from app.rate_limit import limiter  # noqa: E402
from app.seed import seed_demo_plan  # noqa: E402
from app.sqlite_support import (  # noqa: E402
    create_sqlite_engine,
    install_python_defaults,
)
from tests.plaid_server import Plaid, install  # noqa: E402

# Synthetic ledger encryption key for tests that store provider credentials.
LEDGER_KEY = "synthetic-ledger-key-0123456789-abcdef"

# A loaded plug-in may add fixtures and hooks for every test (``<plugin>.testing``).
for _plugin in extensions.loaded:
    try:
        _testing = importlib.import_module(f"{_plugin}.testing")
    except ModuleNotFoundError as _missing:
        if _missing.name != f"{_plugin}.testing":
            raise
    else:
        globals().update({_name: getattr(_testing, _name) for _name in getattr(_testing, "__all__", ())})


@pytest.fixture
def recorded_usage(monkeypatch):
    """Features the routes report to the usage hook (app.usage), in order.
    An installed recorder still receives each one."""
    seen: list[str] = []
    installed = extensions.usage_recorder

    def recorder(db, user_id, feature):
        seen.append(feature)
        if installed is not None:
            installed(db, user_id, feature)

    monkeypatch.setattr(extensions, "usage_recorder", recorder)
    return seen


@pytest.fixture
def transactions_on(monkeypatch):
    """Turn the transactions feature (TRANSACTIONS_ENABLED) on for the test."""
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "true")


@pytest.fixture
def demo_plan(db_session, test_user):
    """The seeded demo plan (app.seed), saved for the test user."""
    created = seed_demo_plan(test_user.id, db_session)
    db_session.commit()
    return created


@pytest.fixture
def plaid(monkeypatch, test_user, db_session):
    """A local Plaid double (tests/plaid_server.py) with transactions, Plaid and
    ledger encryption turned on."""
    for name, value in (("TRANSACTIONS_ENABLED", "true"), ("PLAID_ENABLED", "true"), ("LEDGER_ENCRYPTION_KEY", LEDGER_KEY)):
        monkeypatch.setenv(name, value)
    server = Plaid()
    install(monkeypatch, server)
    return server


@pytest.fixture
def standard_plan():
    """tests/fixtures/standard_plan.json as engine PlanData."""
    return fixture_to_plan_data(load_standard_plan())


@pytest.fixture(autouse=True)
def isolated_rate_limits():
    """Keep the real limiter enabled without sharing request counts across tests."""
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True, scope="session")
def isolated_client_slots(tmp_path_factory):
    """Per-client engine slot locks (app.client_slots) of one test process, not shared with parallel workers."""
    client_slots.LOCK_DIR = tmp_path_factory.mktemp("client_slots")


# ---------------------------------------------------------------------------
# Test DB engine: SQLite, configured as a self-hosted instance configures it
# (app.sqlite_support). In memory unless TEST_SQLITE_DIR names a directory for
# a database file per test worker.
# ---------------------------------------------------------------------------
def _test_engine():
    directory = os.environ.get("TEST_SQLITE_DIR")
    if not directory:
        return create_sqlite_engine("sqlite://", poolclass=StaticPool)
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    return create_sqlite_engine(f"sqlite:///{Path(directory) / f'test_{worker}.db'}")


test_engine = _test_engine()

TestSession = sessionmaker(bind=test_engine)
install_python_defaults(TestSession)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def db_session():
    """Create all tables, seed test user, yield session, then drop."""
    Base.metadata.create_all(bind=test_engine)
    session = TestSession()
    try:
        test_user = User(
            is_anonymous=True,
            email="test@localhost",
            display_name="Test User",
            settings={},
            created_at=datetime.now(UTC),
        )
        session.add(test_user)
        session.commit()
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def test_user(db_session):
    """Return the seeded test user from the DB session."""
    return db_session.query(User).first()


@pytest.fixture
async def client(db_session, test_user):
    """Async HTTP client with test DB and session cookie wired in."""

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    token = create_jwt(test_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"session": token},
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
