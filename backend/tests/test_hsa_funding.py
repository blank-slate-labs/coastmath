"""IRS Pub 15 wage exclusion and CA Schedule CA contribution addback."""

from copy import deepcopy

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import AccountInfo, IncomeData, PriorityData
from tests.corrected_fixture_support import (
    corrected_fixture,
    engine_request,
    persist_fixture,
)
from tests.engine_support import reconcile
from tests.financial_probes import plan


def example(wages=100000, funding="cafeteria", employer=0, state=None):
    return plan(
        birth_year=1986,
        life_expectancy=41,
        tax_settings={
            "hsa_coverage": [
                {
                    "owner": "self",
                    "start_year": 2026,
                    "coverage": "self_only",
                    "payroll_funding": funding,
                }
            ]
        },
        state_code=state,
        accounts={"cash": AccountInfo(10000, "checking"), "h": AccountInfo(0, "hsa")},
        income_streams=[IncomeData("p", "Salary before HSA", wages)],
        priorities=[
            PriorityData(
                1,
                "h",
                3000,
                "income_percent",
                source_income_id="p",
                employee_rate=0.03,
                employer_match_rate=employer,
            )
        ],
    )


@pytest.mark.parametrize(
    "wages,saving",
    [
        (100000, 3000 * 0.0765),
        (185000, 2500 * 0.062 + 3000 * 0.0145),
        (250000, 3000 * (0.0145 + 0.009)),
    ],
)
def test_cafeteria_reduces_owner_fica_wages_before_caps(wages, saving):
    p = example(wages)
    direct = deepcopy(p)
    direct.tax_settings["hsa_coverage"][0]["payroll_funding"] = "direct"
    before = run_simulation(direct).yearly_snapshots[0]
    result = run_simulation(p)
    after = result.yearly_snapshots[0]
    assert before.taxes - after.taxes == pytest.approx(saving, abs=0.01)
    assert after.accounts["h"] == before.accounts["h"] == 3000
    assert after.net_worth - before.net_worth == pytest.approx(saving, abs=0.01)
    reconcile(result)


def test_ca_disallows_employee_deduction_and_taxes_employer_hsa_once():
    p = example(state="CA", employer=0.01)
    r = run_simulation(p)
    s = r.yearly_snapshots[0]
    # Baseline without HSA has the same California income base as employee
    # funding. Employer funding adds $1,000, taxed at 9.3% in this example.
    no_hsa = deepcopy(p)
    no_hsa.priorities = []
    base = run_simulation(no_hsa).yearly_snapshots[0]
    assert s.state_tax - base.state_tax == pytest.approx(93, abs=0.01)
    assert s.accounts["h"] == 4000
    reconcile(r)


@pytest.mark.parametrize("funding", [None, "direct"])
def test_unknown_and_direct_do_not_exclude_fica(funding):
    p = example(funding=funding)
    assert run_simulation(p).yearly_snapshots[0].fica_tax == pytest.approx(7650)


@pytest.mark.parametrize(
    "coverage,months,expected",
    [("ineligible", [], 0), ("self_only", [7, 8, 9, 10, 11, 12], 2200)],
)
def test_months_and_ineligibility_limit_actual_salary_reduction(
    coverage, months, expected
):
    p = example()
    p.tax_settings["hsa_coverage"][0].update(coverage=coverage, eligible_months=months)
    result = run_simulation(p)
    s = result.yearly_snapshots[0]
    assert s.accounts["h"] == pytest.approx(expected)
    assert s.fica_tax == pytest.approx((100000 - expected) * 0.0765)
    reconcile(result)


def test_cafeteria_cannot_use_other_owners_wages_or_self_employment():
    for income in [
        IncomeData("p", "Partner pay", 100000, owner="spouse"),
        IncomeData("p", "Business", 100000, is_self_employed=True),
    ]:
        p = example()
        p.income_streams = [income]
        p.priorities = [PriorityData(1, "h", 3000, "pre_tax_contribution")]
        assert run_simulation(p).yearly_snapshots[0].accounts["h"] == 0


def test_two_earners_keep_separate_wage_caps_and_employer_funding_shared_limit():
    p = example(250000, employer=0.04)
    p.filing_status = "married_filing_jointly"
    p.spouse_birth_year = 1986
    p.accounts["h2"] = AccountInfo(0, "hsa", owner="spouse")
    p.income_streams.append(IncomeData("s", "Partner salary", 100000, owner="spouse"))
    p.tax_settings["hsa_coverage"].append(
        {
            "owner": "spouse",
            "start_year": 2026,
            "coverage": "self_only",
            "payroll_funding": "cafeteria",
        }
    )
    p.priorities.append(
        PriorityData(
            2, "h2", 3000, "income_percent", source_income_id="s", employee_rate=0.03
        )
    )
    r = run_simulation(p)
    s = r.yearly_snapshots[0]
    assert s.accounts["h"] == pytest.approx(
        4400
    )  # $3,000 employee + capped $1,400 employer
    assert s.accounts["h2"] == 3000
    expected = (184500 + 97000) * 0.062 + 344000 * 0.0145 + 94000 * 0.009
    assert s.fica_tax == pytest.approx(expected)
    reconcile(r)


@pytest.mark.anyio
@pytest.mark.parametrize("funding", ["cafeteria", "direct", None])
async def test_funding_persisted_and_stateless(funding, db_session, test_user, client):
    raw = corrected_fixture("high_earner_late_saver")
    raw["life_expectancy"] = 51
    raw["tax_settings"] = {
        "hsa_coverage": [
            {
                "owner": "self",
                "start_year": 2026,
                "coverage": "family",
                "payroll_funding": funding,
            }
        ]
    }
    p = persist_fixture(raw, db_session, test_user)
    a = await client.post(f"/api/plans/{p.plan_id}/simulate")
    b = await client.post(
        "/api/simulate/stateless", json=engine_request(p).model_dump(mode="json")
    )
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
    reconcile(run_simulation(p))


@pytest.mark.parametrize("funding", ["cafeteria", "direct"])
def test_ca_sdi_includes_employee_and_employer_hsa_deposits(funding):
    # EDD DE 231TP page 7: both section 125 and non-125 HSA funding
    # are SDI wages. $100k salary already includes employee $3k;
    # employer $1k is additional taxable state compensation.
    p = example(state="CA", employer=0.01, funding=funding)
    p.tax_settings["state_payroll_coverage"] = [
        {"owner": "self", "start_year": 2026, "state_code": "CA", "ca_sdi": True}
    ]
    result = run_simulation(p)
    s = result.yearly_snapshots[0]
    sdi = sum(x.amount for x in s.cash_flow.expenses if x.name == "California SDI")
    assert sdi == pytest.approx(101000 * 0.013)
    assert s.fica_tax == pytest.approx(
        (97000 if funding == "cafeteria" else 100000) * 0.0765
    )
    reconcile(result)
