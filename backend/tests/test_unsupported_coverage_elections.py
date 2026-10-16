"""Unsupported elections never establish coverage or an extra contribution limit."""
import pytest
from pydantic import ValidationError

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import AccountInfo, IncomeData
from coastmath.engine.waterfall import contribution_room
from coastmath.schemas.coverage_settings import HSACoverage, StatePayrollCoverage
from tests.engine_support import hsa_row, hsa_state
from tests.financial_probes import plan


def test_december_eligibility_does_not_imply_last_month_election():
    s = hsa_state([hsa_row(eligible_months=[12])])
    assert contribution_room("a", s, 40) == pytest.approx(4400 / 12)
    with pytest.raises(ValidationError):
        HSACoverage(**hsa_row(eligible_months=[12]), last_month_rule=True)


@pytest.mark.parametrize("code", ["CA", "WA"])
def test_w2_coverage_does_not_silently_elect_self_employed_programs(code):
    row = dict(owner="self", start_year=2026, state_code=code,
               ca_sdi=code == "CA", wa_paid_leave=code == "WA")
    with pytest.raises(ValidationError):
        StatePayrollCoverage(**row, self_employed_election=True)
    p = plan(birth_year=1986, life_expectancy=41, state_code=code,
             accounts={"cash": AccountInfo(10000, "checking")},
             income_streams=[IncomeData("business", "Business income", 100000, is_self_employed=True)],
             tax_settings={"state_payroll_coverage": [row]})
    s = run_simulation(p).yearly_snapshots[0]
    assert not any(x.amount > 0 for x in s.cash_flow.expenses if x.category == "state_payroll_tax")
