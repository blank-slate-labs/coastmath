"""A taxable account with no recorded basis starts from its opening balance.

Brokerage and crypto accounts whose cost basis is unknown take the opening
balance as basis on the first deposit, withdrawal or reinvested dividend, so
no phantom gain or loss is realized.
"""

import pytest

from coastmath.engine.types import AccountInfo, SimState


@pytest.mark.parametrize("account_type", ["taxable_brokerage", "cryptocurrency"])
def test_nullable_taxable_basis_is_initialized_from_opening_balance_on_deposit(account_type):
    state = SimState(
        year=2026,
        accounts={"account": AccountInfo(1_000.0, account_type)},
    )

    state.deposit_to("account", 200.0)

    assert state.accounts["account"].balance == pytest.approx(1_200.0)
    assert state.accounts["account"].cost_basis == pytest.approx(1_200.0)


@pytest.mark.parametrize("account_type", ["taxable_brokerage", "cryptocurrency"])
def test_nullable_taxable_basis_is_initialized_from_opening_balance_on_withdrawal(account_type):
    state = SimState(
        year=2026,
        accounts={"account": AccountInfo(1_000.0, account_type)},
    )

    state.withdraw_from("account", 100.0)

    assert state.accounts["account"].balance == pytest.approx(900.0)
    assert state.accounts["account"].cost_basis == pytest.approx(900.0)
    assert state.capital_gains_this_year == pytest.approx(0.0)


def test_nullable_basis_preserves_opening_position_when_taxable_dividend_is_reinvested():
    state = SimState(
        year=2026,
        accounts={"brokerage": AccountInfo(1_000.0, "taxable_brokerage")},
    )

    taxable_dividends, cash_interest = state.apply_growth(
        stock_growth_rate=0.0,
        bond_growth_rate=0.0,
        bond_allocation=0.0,
        stock_dividend_yield=0.10,
        cash_yield_rate=0.0,
    )

    assert taxable_dividends == pytest.approx(100.0)
    assert cash_interest == pytest.approx(0.0)
    assert state.accounts["brokerage"].balance == pytest.approx(1_100.0)
    assert state.accounts["brokerage"].cost_basis == pytest.approx(1_100.0)
