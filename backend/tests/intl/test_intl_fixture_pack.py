"""The regime architecture against the test-only pack ``QZ`` (tests/intl_fixture_pack.py):
registry evaluation, the contribution room ledger, account kinds in the catalog,
benefits and the estate rule."""
from __future__ import annotations

import uuid

import pytest

from coastmath.engine import intl_accounts, intl_bridge
from coastmath.engine.intl.evaluator import evaluate
from coastmath.engine.intl.types import EstateInputs, PersonYear, RegimeYearInputs
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    IncomeData,
    PlanData,
    PriorityData,
    SimState,
)
from coastmath.schemas.intl_settings import IntlSettings
from tests.engine_support import reconcile
from tests.intl.helpers import cash


def fixture_plan(**overrides) -> PlanData:
    values = dict(
        plan_id=str(uuid.uuid4()), birth_year=1980, filing_status="single", life_expectancy=50, start_year=2026,
        tax_country="QZ", tax_region="N", currency="EUR",
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0,
                                   stock_dividend_yield=0.0, cash_yield_rate=0.0),
    )
    values.update(overrides)
    return PlanData(**values)


def kind_account(kind: str, balance: float = 0.0) -> AccountInfo:
    return AccountInfo(balance, "other", name=kind, intl_account_kind=f"QZ:{kind}")


def qz_tax(age: int, income: dict[str, float], region: str = "N", year: int = 2026) -> float:
    return evaluate(RegimeYearInputs(country="QZ", year=year, region=region,
                                     people=(PersonYear(person="self", age=age, income=income),))).total


# ---------------------------------------------------------------------------
# Evaluation from registry data
# ---------------------------------------------------------------------------


def test_pack_layers_regions_and_years(fixture_pack):
    """60,000 salary: (60,000 - 10,000) x 20% = 10,000; North 5% = 3,000; social 5% = 3,000."""
    assert qz_tax(45, {"employment": 60_000}) == pytest.approx(16_000)
    # South's regional rate is 8%.
    assert qz_tax(45, {"employment": 60_000}, region="S") == pytest.approx(17_800)
    # 2027 spec: 45% above 50,000 -> 10,000 + 20,000 x 45% + North 4,000 + social 4,000.
    assert qz_tax(45, {"employment": 80_000}, year=2027) == pytest.approx(27_000)
    # Capital gains are half included; no social contribution on them.
    assert qz_tax(45, {"capital_gains": 40_000}) == pytest.approx(10_000 * 0.2 + 20_000 * 0.05)


# ---------------------------------------------------------------------------
# Contribution room ledger
# ---------------------------------------------------------------------------


def _state(accounts: dict[str, AccountInfo], settings: dict | None = None, compensation: float = 0.0) -> SimState:
    state = SimState(year=2026, accounts=accounts)
    state.owner_ages = {"self": 40}
    state.compensation_by_owner = {"self": compensation}
    intl_accounts.configure_room(state, settings)
    intl_accounts.start_year(state, state.owner_ages)
    return state


def _next_year(state: SimState, compensation: float = 0.0) -> None:
    intl_accounts.finish_year(state)
    state.year += 1
    state.owner_ages = {owner: age + 1 for owner, age in state.owner_ages.items()}
    state.ytd_contributions = {}
    state.withdrawals_this_year = {}
    state.compensation_by_owner = {"self": compensation}
    intl_accounts.start_year(state, state.owner_ages)


def _contribute(state: SimState, account_id: str, amount: float) -> None:
    state.ytd_contributions[account_id] = state.ytd_contributions.get(account_id, 0.0) + amount
    state.accounts[account_id].balance += amount


def test_room_starts_from_entered_room_and_carries_forward(fixture_pack):
    state = _state({"free": kind_account("free_saver")}, settings={
        "starting_room": [{"kind": "QZ:free_saver", "owner": "self", "amount": 10_000}]})
    assert intl_accounts.contribution_room("free", state) == pytest.approx(17_000)
    _contribute(state, "free", 5_000)
    _next_year(state)
    assert intl_accounts.contribution_room("free", state) == pytest.approx(12_000 + 7_000)


def test_withdrawal_restores_room_on_the_next_january_1(fixture_pack):
    state = _state({"free": kind_account("free_saver")})
    _contribute(state, "free", 7_000)
    state.withdrawals_this_year["free"] = 3_000
    state.accounts["free"].balance -= 3_000
    assert intl_accounts.contribution_room("free", state) == 0
    _next_year(state)
    assert intl_accounts.contribution_room("free", state) == pytest.approx(3_000 + 7_000)


def test_percent_room_is_capped_by_the_dollar_limit(fixture_pack):
    assert intl_accounts.contribution_room("saver", _state({"saver": kind_account("pension_saver")},
                                                           compensation=50_000)) == pytest.approx(10_000)
    assert intl_accounts.contribution_room("saver", _state({"saver": kind_account("pension_saver")},
                                                           compensation=500_000)) == pytest.approx(20_000)


def test_projection_contributions_are_capped_by_the_ledger(fixture_pack):
    """Salary 100,000 into the free saver with 20,000 entered room: 27,000 the first year, 7,000 after."""
    result = run_simulation(fixture_plan(
        life_expectancy=48,
        income_streams=[IncomeData(id="job", name="Job", annual_amount=100_000, owner="self")],
        accounts={"cash": cash(), "free": kind_account("free_saver")},
        priorities=[PriorityData(1, target_account_id="free")],
        drawdown_order=[DrawdownEntryData(1, "cash")],
        intl_settings={"starting_room": [{"kind": "QZ:free_saver", "owner": "self", "amount": 20_000}]},
    ))
    first, second = result.yearly_snapshots[:2]
    assert first.tax_country == "QZ" and first.federal_tax == 0 and first.state_tax == 0
    assert first.accounts["free"] == pytest.approx(27_000)
    assert second.accounts["free"] == pytest.approx(34_000)
    reconcile(result)


def test_settings_validate_room_entries(fixture_pack):
    settings = IntlSettings.model_validate({"starting_room": [{"kind": "QZ:free_saver", "amount": 5_000}]})
    assert settings.model_dump(mode="json")["starting_room"] == [
        {"kind": "QZ:free_saver", "owner": "self", "amount": 5_000.0}]
    for bad in (
        {"starting_room": [{"kind": "QZ:general", "amount": 1}]},  # no carried room
        {"starting_room": [{"kind": "QZ:nope", "amount": 1}]},
        {"starting_room": [{"kind": "QZ:free_saver", "amount": 1}, {"kind": "QZ:free_saver", "amount": 2}]},
    ):
        with pytest.raises(ValueError):
            IntlSettings.model_validate(bad)


def test_catalog_lists_kinds_with_their_rules(fixture_pack):
    pack = next(c for c in intl_bridge.catalog() if c["code"] == "QZ")
    kinds = {kind["id"]: kind for kind in pack["account_kinds"]}
    assert kinds["QZ:free_saver"]["carries_room"] and not kinds["QZ:general"]["carries_room"]
    assert "Withdrawals are added back to contribution room on the next January 1." in kinds["QZ:free_saver"]["rules"]
    assert "Minimum withdrawals each year from age 72." in kinds["QZ:pension_saver"]["rules"]
    assert [rule["id"] for rule in pack["benefit_rules"]] == ["QZ:basic_pension"]


# ---------------------------------------------------------------------------
# Benefits and death
# ---------------------------------------------------------------------------


def test_benefit_is_paid_and_taxed_as_a_government_pension(fixture_pack):
    plan = fixture_plan(birth_year=1960, life_expectancy=68, accounts={"cash": cash(50_000)},
                        intl_settings={"benefits": [{"rule": "QZ:basic_pension", "start_age": 67,
                                                     "params": {"monthly_amount": 1_000}}]})
    snapshots = {s.year: s for s in run_simulation(plan).yearly_snapshots}
    paid = {year: sum(f.amount for f in s.cash_flow.income_sources if f.name == "Basic pension")
            for year, s in snapshots.items()}
    assert paid[2026] == 0 and paid[2027] == pytest.approx(12_000)
    # 12,000 pension: (12,000 - 10,000) x 20% = 400 national + 600 North tax.
    assert snapshots[2027].national_income_tax + snapshots[2027].regional_income_tax == pytest.approx(1_000)


def test_estate_rule_is_found_through_the_bridge(fixture_pack):
    rule = intl_bridge.estate_rule("QZ")
    inputs = EstateInputs(country="QZ", year=2030, decedent="self", age=80, gross_estate=800_000)
    assert rule.estate_tax(inputs) == pytest.approx(30_000)
    assert intl_bridge.estate_rule("QQ") is None
