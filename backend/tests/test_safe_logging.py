"""Logged exceptions keep their location and drop their (possibly personal) text."""
import pytest
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker

from app.safe_logging import exception_summary

Base = declarative_base()


class Person(Base):
    __tablename__ = "person"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True)


def test_database_errors_lose_their_bound_parameters_and_keep_their_causes():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Person(id=1, email="owner@example.test"))
    session.commit()
    session.add(Person(id=2, email="owner@example.test"))
    with pytest.raises(IntegrityError) as caught:
        session.commit()
    assert "owner@example.test" in str(caught.value)  # SQLAlchemy quotes the parameters.
    summary = exception_summary(caught.value)
    assert "owner@example.test" not in summary and "UNIQUE" not in summary
    assert "sqlalchemy.exc.IntegrityError (message withheld)" in summary
    assert "Caused by: sqlite3.IntegrityError (message withheld)" in summary
    assert "test_database_errors_lose_their_bound_parameters_and_keep_their_causes" in summary


def test_suppressed_context_and_cycles_end_the_chain():
    first, second = (f"{n} private value" for n in ("first", "second"))  # Runtime data, not source text.
    try:
        try:
            raise KeyError(first)
        except KeyError:
            raise ValueError(second) from None
    except ValueError as exc:
        error = exc
    summary = exception_summary(error)
    assert summary.startswith("ValueError (message withheld)") and "KeyError" not in summary
    assert "private" not in summary
    cyclic = RuntimeError("a")
    cyclic.__context__ = RuntimeError("b")
    cyclic.__context__.__context__ = cyclic
    assert exception_summary(cyclic).count("RuntimeError (message withheld)") == 2
