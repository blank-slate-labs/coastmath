"""A test-only country pack, ``QZ`` ("Fixture country"), for the regime architecture.

CoastMath ships no country packs; the registry, evaluator, account kinds,
benefits and estate rules are covered against this pack instead. Its data is
``tests/fixtures/tax_regimes/QZ/<YEAR>.json`` (every figure invented); the
``fixture_pack`` fixture points the registry at that directory and registers
the pack's rules for one test:

- income tax: a 10,000 allowance, then 20% to 50,000 and 40% above (45% from
  2027); region ``N`` adds 5% and ``S`` 8% (no allowance); employment income
  pays a 5% social contribution; capital gains are half included;
- account kinds ``pension_saver`` (tax-deferred, deductible, room of 20% of
  earned income up to 20,000 that carries forward, minimum withdrawals from
  72), ``free_saver`` (tax-free, 7,000 room that carries forward and is
  restored by withdrawals), ``general`` (taxable), ``workplace_pension`` and
  ``private_pension`` (a shared 60,000 allowance, at most 100% of earnings from
  the member's own contributions; employer money only in the workplace one),
  ``taxed_pension`` (32,500, 15% tax on contributions, employer money allowed)
  and ``after_tax_saver`` (tax-free, 130,000);
- benefit ``QZ:basic_pension``: ``monthly_amount`` x 12 from ``start_age``;
- estate rule: 10% of a gross estate above 500,000, none with a surviving spouse.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, Field

from coastmath.engine.intl import plugins, registry
from coastmath.engine.intl.types import BenefitContext, BenefitYear, EstateInputs

FIXTURE_COUNTRY = "QZ"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "tax_regimes"
PENSION_RULE = "QZ:basic_pension"


class BasicPensionParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monthly_amount: float = Field(default=0.0, ge=0, le=1_000_000)


class BasicPension:
    id = PENSION_RULE
    label = "Basic pension"
    params_model = BasicPensionParams

    def annual_amount(self, ctx: BenefitContext) -> BenefitYear:
        if ctx.start_age is None or ctx.age < ctx.start_age:
            return BenefitYear(0.0)
        return BenefitYear(ctx.params.monthly_amount * 12)


class FixtureEstate:
    country = FIXTURE_COUNTRY

    def estate_tax(self, inputs: EstateInputs) -> float:
        if inputs.surviving_spouse:
            return 0.0
        return max(0.0, inputs.gross_estate - 500_000) * 0.10


def _clear_registry_caches() -> None:
    for cached in (registry._pack_codes, registry._pack_files, registry._load_file, registry._country_info):
        cached.cache_clear()


@pytest.fixture
def fixture_pack(monkeypatch):
    """The registry lists ``QZ`` (and ``XX``) while the test runs."""
    plugins.discover()
    monkeypatch.setattr(plugins, "_BENEFIT_RULES", dict(plugins._BENEFIT_RULES))
    monkeypatch.setattr(plugins, "_ESTATE_RULES", dict(plugins._ESTATE_RULES))
    plugins.register_benefit_rule(BasicPension)
    plugins.register_estate_rule(FixtureEstate)
    monkeypatch.setattr(registry, "DATA_DIR", FIXTURE_DIR)
    _clear_registry_caches()
    yield FIXTURE_COUNTRY
    _clear_registry_caches()
