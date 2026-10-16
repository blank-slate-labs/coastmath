"""Rule registration refuses conflicting or malformed rules; discovery reads module lists."""
from __future__ import annotations

import importlib
import sys
import textwrap
import threading

import pytest

from coastmath.engine.intl import plugins, types
from coastmath.engine.intl.spec import (
    AccountKindSpec,
    TransactionTaxSpec,
    WealthTaxSpec,
)
from coastmath.engine.intl.types import EstateInputs, RegimeOverrides


@pytest.fixture
def isolated_registry(monkeypatch):
    """Registrations made by a test vanish afterwards."""
    monkeypatch.setattr(plugins, "_TAX_RULES", dict(plugins._TAX_RULES))
    monkeypatch.setattr(plugins, "_BENEFIT_RULES", dict(plugins._BENEFIT_RULES))
    monkeypatch.setattr(plugins, "_ESTATE_RULES", dict(plugins._ESTATE_RULES))


class _Estate:
    country = "QQ"

    def estate_tax(self, inputs) -> float:
        return 0.0


class _OtherEstate(_Estate):
    pass


class _Benefit:
    id = "QQ:pension"
    label = "Pension"
    params_model = None

    def annual_amount(self, ctx):
        raise NotImplementedError


class _OtherBenefit(_Benefit):
    pass


def _rule(ctx):
    return plugins.RuleOutput()


def test_an_unknown_rule_phase_is_rejected(isolated_registry) -> None:
    with pytest.raises(ValueError, match="unknown rule phase 'later'"):
        plugins.register_tax_rule("QQ:late", phase="later")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown rule phase 'later'"):
        plugins.add_tax_rule(plugins.TaxRule(id="QQ:late", phase="later", fn=_rule))  # type: ignore[arg-type]
    assert plugins.tax_rule("QQ:late") is None


def test_a_rule_id_cannot_be_registered_twice_with_different_code(isolated_registry) -> None:
    plugins.add_tax_rule(plugins.TaxRule(id="QQ:credit", phase="final", fn=_rule))
    plugins.add_tax_rule(plugins.TaxRule(id="QQ:credit", phase="final", fn=_rule))  # same code: idempotent
    # The lambda is a different function with the same behavior.
    with pytest.raises(ValueError, match="tax rule 'QQ:credit' is registered twice"):
        plugins.add_tax_rule(plugins.TaxRule(id="QQ:credit", phase="final", fn=lambda ctx: _rule(ctx)))  # noqa: PLW0108


def test_benefit_and_estate_rules_must_be_unique_per_id(isolated_registry) -> None:
    assert plugins.register_benefit_rule(_Benefit) is _Benefit
    plugins.register_benefit_rule(_Benefit())  # same type again: idempotent
    with pytest.raises(ValueError, match="benefit rule 'QQ:pension' is registered twice"):
        plugins.register_benefit_rule(_OtherBenefit)
    assert plugins.register_estate_rule(_Estate) is _Estate
    with pytest.raises(ValueError, match="estate rule for 'QQ' is registered twice"):
        plugins.register_estate_rule(_OtherEstate)


def test_objects_without_the_rule_interface_are_rejected(isolated_registry) -> None:
    with pytest.raises(TypeError, match="does not implement BenefitRule"):
        plugins.register_benefit_rule(object())
    with pytest.raises(TypeError, match="does not implement EstateRule"):
        plugins.register_estate_rule(object())


def test_discovery_registers_module_level_rule_lists(isolated_registry, monkeypatch, tmp_path) -> None:
    package = tmp_path / "qq_rules"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "_private.py").write_text("raise AssertionError('private modules are not imported')\n")
    (package / "qq.py").write_text(textwrap.dedent("""
        from coastmath.engine.intl.plugins import RuleOutput, TaxRule
        from tests.intl.test_plugin_registration_boundaries import _Benefit, _Estate

        TAX_RULES = [TaxRule(id="QQ:listed", phase="final", fn=lambda ctx: RuleOutput())]
        BENEFIT_RULES = [_Benefit]
        ESTATE_RULES = [_Estate()]
    """))
    monkeypatch.syspath_prepend(str(tmp_path))
    real_import = importlib.import_module

    def import_module(name: str):
        return real_import("qq_rules" if name == "coastmath.engine.intl.rules" else name)

    monkeypatch.setattr(plugins.importlib, "import_module", import_module)
    monkeypatch.setattr(plugins, "_discovered", threading.Event())
    try:
        plugins.discover()
        assert plugins.tax_rule("QQ:listed") is not None
        assert isinstance(plugins._BENEFIT_RULES["QQ:pension"], _Benefit)
        assert isinstance(plugins._ESTATE_RULES["QQ"], _Estate)
        assert plugins._discovered.is_set()
    finally:
        for name in ("qq_rules", "qq_rules.qq"):
            sys.modules.pop(name, None)


def test_overrides_given_as_stored_dicts_are_validated() -> None:
    overrides = RegimeOverrides(wealth_tax={"rate": 0.01}, transaction_tax={"rate": 0.002})
    assert isinstance(overrides.wealth_tax, WealthTaxSpec)
    assert isinstance(overrides.transaction_tax, TransactionTaxSpec)
    assert overrides.transaction_tax.rate == 0.002


def test_unknown_death_gain_categories_are_rejected() -> None:
    with pytest.raises(ValueError, match=r"unknown unrealized gain categories \['crypto'\]"):
        EstateInputs(country="QQ", year=2030, decedent="self", age=90, gross_estate=1.0,
                     unrealized_gains={"crypto": 1.0})
    inputs = EstateInputs(country="QQ", year=2030, decedent="self", age=90, gross_estate=1.0,
                          unrealized_gains={"taxable": 5})
    assert inputs.unrealized_gains == {"taxable": 5.0}


def test_account_kind_spec_is_reexported_and_other_names_are_not() -> None:
    assert types.AccountKindSpec is AccountKindSpec
    with pytest.raises(AttributeError):
        types.NotAType  # noqa: B018
