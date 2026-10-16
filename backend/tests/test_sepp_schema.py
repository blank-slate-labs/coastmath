"""Tests for SEPPSettings Pydantic schema validation."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.sepp_settings import SEPPSettings


def _valid_sepp(**overrides) -> dict:
    base = {
        "enabled": True,
        "source_account_id": str(uuid.uuid4()),
        "method": "fixed_amortization",
        "start_age": 55.0,
        "interest_rate": 0.05,
    }
    base.update(overrides)
    return base


class TestSEPPSettingsValid:
    def test_valid_enabled(self):
        s = SEPPSettings(**_valid_sepp())
        assert s.enabled is True
        assert s.start_age == 55.0
        assert s.method == "fixed_amortization"

    def test_valid_disabled(self):
        s = SEPPSettings(enabled=False, start_age=50.0)
        assert s.enabled is False
        assert s.source_account_id is None

    def test_supported_methods(self):
        for method in ("fixed_amortization", "rmd_method"):
            s = SEPPSettings(**_valid_sepp(method=method))
            assert s.method == method

    def test_annuitization_rejected_when_enabled_but_kept_when_disabled(self):
        """The bundled mortality table is approximate, so annuitization cannot
        drive projections; a disabled legacy record still parses."""
        with pytest.raises(ValidationError):
            SEPPSettings(**_valid_sepp(method="fixed_annuitization"))
        s = SEPPSettings(**{**_valid_sepp(method="fixed_annuitization"), "enabled": False})
        assert s.method == "fixed_annuitization"

    def test_boundary_start_age(self):
        s = SEPPSettings(**_valid_sepp(start_age=59.4))
        assert s.start_age == 59.4

    def test_boundary_interest_rate(self):
        s = SEPPSettings(**_valid_sepp(interest_rate=0.0))
        assert s.interest_rate == 0.0
        s = SEPPSettings(**_valid_sepp(interest_rate=0.15))
        assert s.interest_rate == 0.15


class TestSEPPSettingsInvalid:
    def test_start_age_at_59_5_rejected(self):
        with pytest.raises(ValidationError, match="start_age must be less than 59.5"):
            SEPPSettings(**_valid_sepp(start_age=59.5))

    def test_start_age_above_59_5_rejected(self):
        with pytest.raises(ValidationError, match="start_age must be less than 59.5"):
            SEPPSettings(**_valid_sepp(start_age=65.0))

    def test_interest_rate_negative_rejected(self):
        with pytest.raises(ValidationError, match="interest_rate must be between 0 and 0.15"):
            SEPPSettings(**_valid_sepp(interest_rate=-0.01))

    def test_interest_rate_above_max_rejected(self):
        with pytest.raises(ValidationError, match="interest_rate must be between 0 and 0.15"):
            SEPPSettings(**_valid_sepp(interest_rate=0.20))

    def test_invalid_method_rejected(self):
        with pytest.raises(ValidationError):
            SEPPSettings(**_valid_sepp(method="invalid_method"))

    def test_enabled_without_source_account_rejected(self):
        with pytest.raises(ValidationError, match="source_account_id is required"):
            SEPPSettings(
                enabled=True,
                source_account_id=None,
                method="fixed_amortization",
                start_age=55.0,
            )

    def test_disabled_without_source_account_ok(self):
        s = SEPPSettings(
            enabled=False,
            source_account_id=None,
            method="rmd_method",
            start_age=50.0,
        )
        assert s.source_account_id is None
