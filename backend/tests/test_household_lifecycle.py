"""Opt-in household accounting and bounded survivor election."""

import uuid
from copy import deepcopy
from dataclasses import asdict

import pandas as pd
import pytest
from pydantic import ValidationError

from app.schemas.estate_settings import EstateSettings
from coastmath.engine.historical_stress import run_historical_stress_test
from coastmath.engine.household_lifecycle import (
    LAST_SURVIVOR,
    apply_transitions,
    longevity_end_month_index,
    owner_alive_until,
    simulation_end_year,
    tax_ages,
)
from coastmath.engine.monte_carlo import run_monte_carlo
from coastmath.engine.simulator import run_simulation
from coastmath.engine.survivor_social_security import survivor_fra_months
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    EstateSettingsData,
    ExpenseData,
    IncomeData,
    PlanData,
    SimState,
)
from coastmath.schemas.plan_data_request import PlanDataRequest, request_to_engine_data
from tests.api_support import create_plan


def plan(**changes):
    values = dict(
        plan_id=str(uuid.uuid4()),
        birth_year=1950,
        birth_month=1,
        life_expectancy=76,
        spouse_birth_year=1952,
        spouse_birth_month=7,
        spouse_life_expectancy=78,
        filing_status="married_filing_jointly",
        start_year=2026,
        estate_settings=EstateSettingsData(household_lifecycle=LAST_SURVIVOR),
        assumptions=AssumptionData(
            inflation_rate=0,
            stock_growth_rate=0,
            bond_return_rate=0,
            stock_dividend_yield=0,
            cash_yield_rate=0,
        ),
        accounts={"cash": AccountInfo(balance=100000, account_type="checking")},
        tax_settings={
            "mode": "flat",
            "ordinary_income_tax_rate": 0,
            "capital_gains_tax_rate": 0,
        },
    )
    values.update(changes)
    return PlanData(**values)


def ss(owner, amount, claim=67, active=True):
    return IncomeData(
        id=owner + "_ss",
        name=owner + " SS",
        owner=owner,
        annual_amount=amount,
        is_social_security=True,
        is_earned_income=False,
        claiming_age=claim,
        is_active=active,
    )


def policy(p):
    p.estate_settings.survivor_social_security_policy = (
        "claimed_benefit_at_survivor_fra"
    )
    p.estate_settings.survivor_social_security_eligibility_confirmed = True
    p.estate_settings.survivor_social_security_eligibility_source = (
        "Synthetic independently supplied eligibility fixture"
    )
    return p


def test_real_continuation_stops_only_deceased_income():
    p = plan(
        income_streams=[
            IncomeData(id="a", name="self salary", annual_amount=10000, owner="self"),
            IncomeData(
                id="b", name="spouse salary", annual_amount=20000, owner="spouse"
            ),
        ]
    )
    original = deepcopy(p)
    result = run_simulation(p)
    assert [r.year for r in result.yearly_snapshots] == list(range(2026, 2031))
    assert [r.gross_income for r in result.yearly_snapshots] == [
        30000,
        20000,
        20000,
        20000,
        20000,
    ]
    assert result.yearly_snapshots[-1].net_worth > result.yearly_snapshots[0].net_worth
    assert result.metadata.net_legacy.marital_deduction_applied is False
    assert result.metadata.net_legacy.death_year == 2030
    assert p == original


@pytest.mark.parametrize("deceased", ["self", "spouse"])
def test_next_january_transfer_preserves_roth_and_owner_age(deceased):
    p = plan()
    if deceased == "spouse":
        p.life_expectancy, p.spouse_life_expectancy = 80, 74
    survivor = "spouse" if deceased == "self" else "self"
    history = {
        "contribution_basis": 5000,
        "first_contribution_year": 2010,
        "conversions": [{"year": 2025, "taxable_basis": 1000, "nontaxable_basis": 200}],
    }
    state = SimState(
        year=2026,
        accounts={
            "roth": AccountInfo(
                balance=10000,
                account_type="roth_ira",
                owner=deceased,
                roth_settings=deepcopy(history),
            ),
            "taxable": AccountInfo(
                balance=15000,
                account_type="taxable_brokerage",
                owner=deceased,
                cost_basis=3000,
            ),
            "joint": AccountInfo(
                balance=8000,
                account_type="taxable_brokerage",
                owner="joint",
                cost_basis=4000,
            ),
        },
    )
    apply_transitions(p, state, 2026)
    assert state.accounts["roth"].owner == deceased
    assert owner_alive_until(p, state, deceased, 2026) == 1
    apply_transitions(p, state, 2027)
    assert state.accounts["roth"].owner == survivor
    assert state.accounts["roth"].roth_settings == history
    assert state.accounts["taxable"].cost_basis == 15000
    assert state.accounts["joint"].cost_basis == 4000
    assert owner_alive_until(p, state, deceased, 2027) == 0
    assert state.current_filing_status == "single"
    assert tax_ages(p, state, 2027) == (
        2027 - (p.spouse_birth_year if deceased == "self" else p.birth_year),
        None,
    )
    first = deepcopy(state)
    apply_transitions(p, state, 2028)
    assert state.accounts == first.accounts


def test_survivor_age_drives_retirement_withdrawal_penalty():
    p = plan(
        spouse_birth_year=1980,
        spouse_life_expectancy=50,
        accounts={
            "ira": AccountInfo(
                balance=100000, account_type="traditional_ira", owner="self"
            )
        },
        # Above the primary's $4,219 RMD at 76, so no surplus is banked as
        # generated cash and the survivor's spending reaches the IRA.
        expenses=[
            ExpenseData(
                id="e", name="living", annual_amount=5000, inflation_linked=False
            )
        ],
        drawdown_order=[DrawdownEntryData(source_account_id="ira", rank=1)],
    )
    result = run_simulation(p)
    assert result.yearly_snapshots[0].early_withdrawal_penalty == 0
    assert result.yearly_snapshots[1].early_withdrawal_penalty > 0


def test_simultaneous_death_no_false_survivor_or_portability():
    result = run_simulation(plan(spouse_life_expectancy=74))
    assert result.metadata.end_year == 2026
    assert result.metadata.net_legacy.marital_deduction_applied is False
    assert result.metadata.net_legacy.dsue_amount == 0


def test_missing_longevity_rejected_legacy_unchanged():
    p = plan(spouse_life_expectancy=None)
    with pytest.raises(ValueError, match="spouse longevity"):
        run_simulation(p)
    p.estate_settings = None
    assert simulation_end_year(p) == 2026
    p.start_year = 2025
    legacy = run_simulation(p).model_dump()
    p.estate_settings = EstateSettingsData()
    assert run_simulation(p).model_dump() == legacy


def test_stateless_roundtrip_and_last_year_start():
    p = plan()
    restored = request_to_engine_data(PlanDataRequest.model_validate(asdict(p)))
    assert restored.estate_settings.household_lifecycle == LAST_SURVIVOR
    assert simulation_end_year(restored) == 2031
    assert longevity_end_month_index(restored, "self") == 2027 * 12
    invalid = asdict(p)
    invalid["spouse_life_expectancy"] = None
    with pytest.raises(ValidationError, match="spouse longevity"):
        PlanDataRequest.model_validate(invalid)


@pytest.mark.parametrize(
    "year,months",
    [
        (1939, 780),
        (1940, 782),
        (1945, 792),
        (1956, 792),
        (1957, 794),
        (1960, 800),
        (1961, 802),
        (1962, 804),
    ],
)
def test_survivor_fra_cohorts(year, months):
    assert survivor_fra_months(year) == months


@pytest.mark.parametrize("own,expected", [(10000, 30000), (40000, 40000), (0, 30000)])
def test_survivor_higher_not_sum_and_cola(own, expected):
    p = policy(
        plan(income_streams=[ss("self", 30000), ss("spouse", own, active=own > 0)])
    )
    assert run_simulation(p).yearly_snapshots[1].gross_income == expected
    p.income_streams[0].growth_rate = 0.03
    assert run_simulation(p).yearly_snapshots[1].gross_income == pytest.approx(
        max(own, 30900)
    )


def test_survivor_fra_month_only_eligible_overlap():
    # July1960 plus66y8m is March2027: ten months of survivor top-up.
    p = policy(
        plan(
            spouse_birth_year=1960,
            spouse_life_expectancy=70,
            income_streams=[ss("self", 30000), ss("spouse", 12000, claim=62)],
        )
    )
    assert run_simulation(p).yearly_snapshots[1].gross_income == pytest.approx(
        12000 + (30000 - 12000) * 10 / 12
    )


@pytest.mark.parametrize("reason", ["early", "unclaimed", "ambiguous", "eligibility"])
def test_unsupported_survivor_rejected(reason):
    p = policy(plan(income_streams=[ss("self", 30000)]))
    if reason == "early":
        p.income_streams[0].claiming_age = 62
    elif reason == "unclaimed":
        p.income_streams[0].claiming_age = 80
    elif reason == "ambiguous":
        p.income_streams.append(ss("self", 10000))
    else:
        p.estate_settings.survivor_social_security_eligibility_confirmed = False
    with pytest.raises(ValueError):
        run_simulation(p)


def test_disabled_policy_keeps_spouse_benefit_disabled():
    result = run_simulation(
        plan(income_streams=[ss("self", 30000), ss("spouse", 20000, active=False)])
    )
    assert result.yearly_snapshots[1].gross_income == 0
    assert any("survivor benefits are off" in w for w in result.metadata.warnings)


def test_stress_and_monte_carlo_keep_real_survivor_years():
    history = pd.DataFrame(
        {
            "year": list(range(2000, 2010)),
            "stock_return": [0.0] * 10,
            "bond_return": [0.0] * 10,
            "inflation": [0.0] * 10,
        }
    )
    p = plan(
        income_streams=[
            IncomeData(id="sp", name="survivor", owner="spouse", annual_amount=10000)
        ]
    )
    stress = run_historical_stress_test(p, 2000, history)
    assert stress["metadata"]["years_used"] == list(range(2000, 2005))
    assert stress["simulation_result"].yearly_snapshots[-1].gross_income == 10000
    mc = run_monte_carlo(p, n_trials=2, historical_data=history, max_workers=1, seed=42)
    assert mc.percentile_curves.years == list(range(2026, 2031))


def test_estate_legacy_serialization_preserves_omission_and_explicit_opt_in():
    legacy = EstateSettings.model_validate({"step_up_basis_on_death": False})
    assert "household_lifecycle" not in legacy.model_dump()
    explicit = EstateSettings.model_validate(
        {"household_lifecycle": LAST_SURVIVOR, "survivor_social_security_policy": "off"}
    )
    assert explicit.model_dump()["household_lifecycle"] == LAST_SURVIVOR
    assert explicit.model_dump()["survivor_social_security_policy"] == "off"


@pytest.mark.anyio
async def test_persisted_lifecycle_roundtrip_runs_survivor_endpoint(client):
    saved = await create_plan(
        client,
        birth_year=1950,
        life_expectancy=76,
        filing_status="married_filing_jointly",
    )
    response = await client.put(
        f"/api/plans/{saved['id']}",
        json={
            "estate_settings": {"household_lifecycle": LAST_SURVIVOR},
            "spouse": {"name": "Survivor", "birth_year": 1952, "life_expectancy": 78},
        },
    )
    assert response.status_code == 200
    reopened = await client.get(f"/api/plans/{saved['id']}")
    assert reopened.json()["estate_settings"]["household_lifecycle"] == LAST_SURVIVOR
    result = await client.post(f"/api/plans/{saved['id']}/simulate")
    assert result.status_code == 200, result.text
    assert result.json()["metadata"]["end_year"] == 2030
    assert result.json()["metadata"]["net_legacy"]["marital_deduction_applied"] is False


def test_transferred_ira_uses_younger_survivor_rmd_age():
    p = plan(
        spouse_birth_year=1980,
        spouse_life_expectancy=50,
        accounts={
            "ira": AccountInfo(
                balance=100000, account_type="traditional_ira", owner="self"
            )
        },
    )
    rows = run_simulation(p).yearly_snapshots
    assert next(
        x.amount for x in rows[0].cash_flow.income_sources if x.name == "RMD"
    ) == pytest.approx(100000 / 23.7)
    assert all(x.name != "RMD" for x in rows[1].cash_flow.income_sources)


def test_inherited_ira_paid_out_before_death_allows_survivor_continuation():
    p = plan(life_expectancy=78, accounts={
        "ira": AccountInfo(100000, "traditional_ira", owner="self", inherited_year=2016,
                           inheritance_settings={"distribution_method": "ten_year", "decedent_died_after_rbd": False}),
    })
    rows = run_simulation(p).yearly_snapshots
    assert rows[-1].year == 2030
    assert all(r.accounts["ira"] == 0 for r in rows)
    assert rows[0].gross_income == pytest.approx(100000)


def test_positive_inherited_successor_rejected_at_actual_transition_atomically():
    p = plan()
    state = SimState(year=2026, accounts={"ira": AccountInfo(100, "traditional_ira", owner="self", inherited_year=2025)})
    before = deepcopy(state)
    assert simulation_end_year(p) == 2031
    with pytest.raises(ValueError, match="successor beneficiary"):
        apply_transitions(p, state, 2027)
    assert state == before
    state.accounts["ira"].balance = 0
    apply_transitions(p, state, 2027)
    assert state.primary_deceased
    assert state.accounts["ira"].owner == "spouse"


def test_single_calendar_year_endpoint_is_explicit_and_legacy_unchanged():
    p = plan(birth_year=1950, life_expectancy=80, spouse_birth_year=None,
             spouse_birth_month=None, spouse_life_expectancy=None, filing_status="single")
    explicit = run_simulation(p)
    assert [r.year for r in explicit.yearly_snapshots] == list(range(2026, 2031))
    assert [r.net_worth for r in explicit.yearly_snapshots] == [100000] * 5
    p.estate_settings = None
    legacy = run_simulation(p).model_dump()
    p.estate_settings = EstateSettingsData()
    assert run_simulation(p).model_dump() == legacy
    assert legacy["metadata"]["end_year"] == 2029
