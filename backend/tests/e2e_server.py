"""Local browser-test server using the pytest SQLite fixtures, never a real DB.

Run from backend with: venv/bin/python -m tests.e2e_server
The database lives only for this process. PostgreSQL migrations and locking
remain covered by the separate PostgreSQL integration tests.
"""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

# Set before importing the app so dotenv cannot select a developer/remote DB.
os.environ["DATABASE_URL"] = ""
os.environ["SESSION_SECRET"] = "dev-secret-change-me-local-development-only"  # app.auth.config.DEV_SESSION_SECRET

from importlib import import_module  # noqa: E402

import uvicorn  # noqa: E402
from fastapi import Depends  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from app.auth.dependencies import get_current_user  # noqa: E402
from app.plugins import extensions  # noqa: E402
from app.seed import seed_demo_plan, seed_sample_household  # noqa: E402
from tests.conftest import Base, TestSession, app, get_db  # noqa: E402


def browser_test_db():
    with TestSession() as session:
        yield session


def install_sample_plan(app):
    """``POST /api/__sample_plan`` gives this browser's session the sample plan.

    Sessions stopped seeding it when signed-out ``/sample`` became a static
    read-only page. Workflows that edit a real saved plan create a session, then
    request this. Like the former session seeding, the plan's accounts belong to
    the user unless ``{"client_workspace": true}`` asks for the sample household.
    Registered only by this test server.
    """
    class SamplePlanRequest(BaseModel):
        client_workspace: bool = False

    @app.post("/api/__sample_plan", status_code=201)
    def sample_plan(body: SamplePlanRequest | None = None, user=Depends(get_current_user), db=Depends(get_db)):
        plan = seed_sample_household(user.id, db) if body and body.client_workspace else seed_demo_plan(user.id, db)
        return {"plan_id": str(plan.id)}


def install_plugin_fixtures(app):
    """Each loaded plug-in's own browser fixtures (``tests/<plugin>/e2e_fixtures.py``)."""
    for plugin in extensions.loaded:
        try:
            fixtures = import_module(f"tests.{plugin}.e2e_fixtures")
        except ModuleNotFoundError as missing:
            if missing.name != f"tests.{plugin}.e2e_fixtures":
                raise
        else:
            fixtures.install(app, get_db)


if __name__ == "__main__":
    install_sample_plan(app)
    install_plugin_fixtures(app)
    # Separate connections are required for concurrent browser HTTP requests.
    with TemporaryDirectory(prefix="coastmath-browser-tests-") as directory:
        engine = create_engine(f"sqlite:///{Path(directory) / 'test.db'}")
        TestSession.configure(bind=engine)
        Base.metadata.create_all(bind=engine)
        app.dependency_overrides[get_db] = browser_test_db
        app.state.limiter.enabled = False  # Many fresh sessions in a short run.
        # The schema comes from create_all above, not from the startup migrations.
        try:
            uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("E2E_PORT", "4174")), lifespan="off")
        finally:
            engine.dispose()
