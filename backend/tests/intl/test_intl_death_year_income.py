"""A person who dies during a country year still files that year's return: their income up to
death is taxed, separately from any tax the country charges because of the death itself."""
from __future__ import annotations

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import DrawdownEntryData
from tests.intl.helpers import cash
from tests.intl.test_intl_fixture_pack import fixture_plan, kind_account, qz_tax


def test_decedents_own_income_is_taxed_in_the_death_year(fixture_pack):
    plan = fixture_plan(
        birth_year=1950, life_expectancy=77,  # one year: 2026, at 76
        accounts={"cash": cash(100_000), "saver": kind_account("pension_saver", 2_000_000)},
        drawdown_order=[DrawdownEntryData(1, "cash")],
    )
    result = run_simulation(plan)
    last = result.yearly_snapshots[-1]
    minimum = sum(f.amount for f in last.cash_flow.income_sources if f.source == "rmd")
    country_tax = (last.national_income_tax + last.regional_income_tax
                   + last.social_contributions + last.benefit_recovery_tax)
    assert minimum == pytest.approx(2_000_000 * 0.05)
    assert country_tax == pytest.approx(qz_tax(76, {"retirement_withdrawal": minimum}))
    assert country_tax > 0
