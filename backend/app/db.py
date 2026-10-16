import os
from collections.abc import Generator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.errors import api_error
from app.sqlite_support import (
    create_sqlite_engine,
    install_python_defaults,
    is_sqlite_url,
)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL: str | None = os.environ.get("DATABASE_URL")

engine: Engine | None = None
SessionLocal: sessionmaker | None = None

if DATABASE_URL:
    if is_sqlite_url(DATABASE_URL):
        engine = create_sqlite_engine(DATABASE_URL)
        SessionLocal = sessionmaker(bind=engine)
        install_python_defaults(SessionLocal)
    else:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session]:
    if SessionLocal is None:
        raise api_error(503, "HTTP_503", "Database not configured.")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
