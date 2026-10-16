"""The country-regime bridge degrades to "not available" instead of raising.

A registry that does not know a country, kind or rule, or a server without the
regime package, must give empty answers to catalog lookups and a clear error to
calls that need the package.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from coastmath.engine import intl_bridge


class _Unknown(LookupError):
    pass


class _Registry:
    """Lists two countries by code; it knows only "QQ" and one of its rules."""

    def list_countries(self):
        return ["QQ", "ZQ"]

    def get_country(self, code):
        if code != "QQ":
            raise _Unknown(code)
        return {"code": "QQ", "name": "Q-land", "currency": "QQD", "filing_unit": "individual",
                "benefit_rules": ["QQ:pension", "QQ:retired_rule"]}

    def account_kinds(self, code):
        if code != "QQ":
            raise KeyError(code)
        return [{"id": "QQ:saver", "label": "Saver", "category": "tax_free",
                 "converts_to": {"kind_id": "annuity", "age": 75}}]

    def benefit_rule(self, rule_id):
        if rule_id != "QQ:pension":
            raise ValueError(rule_id)
        return SimpleNamespace(id=rule_id, label="Pension", params_model=None)

    def estate_rule(self, code):
        raise KeyError(code)


@pytest.fixture
def registry():
    intl_bridge.use_package(SimpleNamespace(registry=_Registry()))
    try:
        yield
    finally:
        intl_bridge.use_package(None)


def test_unknown_countries_are_left_out_of_the_catalog(registry) -> None:
    assert list(intl_bridge.countries()) == ["QQ"]
    assert intl_bridge.country("ZQ") is None
    assert not intl_bridge.is_known_country("ZQ")


def test_unregistered_benefit_rules_are_left_out_of_the_catalog(registry) -> None:
    (entry,) = intl_bridge.catalog()
    assert [rule["id"] for rule in entry["benefit_rules"]] == ["QQ:pension"]
    assert entry["benefit_rules"][0]["params_schema"] == {}


def test_a_qualified_kind_id_is_normalized_once(registry) -> None:
    (kind,) = intl_bridge.account_kinds("QQ")
    assert (kind.ref, kind.id, kind.converts_to, kind.converts_at_age) == ("QQ:saver", "saver", "QQ:annuity", 75.0)
    assert intl_bridge.account_kind("QQ:saver") == kind


def test_lookups_the_registry_rejects_return_nothing(registry) -> None:
    assert intl_bridge.account_kinds("ZQ") == ()
    assert intl_bridge.account_kind("ZQ:saver") is None
    assert intl_bridge.account_kind(None) is None
    assert intl_bridge.account_kind("saver") is None
    assert intl_bridge.benefit_rule("QQ:retired_rule") is None
    assert intl_bridge.estate_rule("QQ") is None
    with pytest.raises(ValueError, match="Unknown benefit rule 'QQ:retired_rule'"):
        intl_bridge.benefit_params("QQ:retired_rule", {})


def test_without_the_regime_package_lookups_are_empty_and_evaluation_fails(monkeypatch) -> None:
    monkeypatch.setattr(intl_bridge, "package", lambda: None)
    assert intl_bridge.countries() == {}
    assert intl_bridge.catalog() == []
    assert intl_bridge.account_kinds("QQ") == ()
    assert intl_bridge.benefit_rule("QQ:state_pension") is None
    assert intl_bridge.estate_rule("QQ") is None
    with pytest.raises(ValueError, match="not available on this server"):
        intl_bridge.custom_spec({})
    with pytest.raises(ValueError, match="not available on this server"):
        intl_bridge.spec_base_year("QQ", 2030)


def test_section_overrides_are_validated_by_the_spec_section_model() -> None:
    wealth = intl_bridge.validate_spec_section("wealth_tax", {"rate": 0.01})
    assert wealth.rate == 0.01
    with pytest.raises(ValidationError):
        intl_bridge.validate_spec_section("wealth_tax", {"rate": 0.01, "unknown": 1})
    with pytest.raises(ValueError, match="The regime has no estate_tax section"):
        intl_bridge.validate_spec_section("estate_tax", {"rate": 0.4})
