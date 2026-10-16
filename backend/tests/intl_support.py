"""Fixture that installs the country regime test double (tests/intl_double.py)."""
import pytest

from coastmath.engine import intl_bridge
from tests import intl_double


@pytest.fixture
def intl_double_package():
    intl_double.CALLS.clear()
    intl_bridge.use_package(intl_double.namespace())
    try:
        yield intl_double
    finally:
        intl_bridge.use_package(None)
