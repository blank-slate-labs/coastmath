"""HSA and state payroll coverage: statutory amounts, eligibility negatives and wire validation."""
import pytest
from pydantic import ValidationError

from app.schemas.plan import TaxSettings
from coastmath.engine.coverage_rules import (
    hsa_contribution_room,
    state_payroll_obligations,
)
from coastmath.engine.types import PriorityData
from coastmath.engine.waterfall import allocate_payroll_contributions, contribution_room
from coastmath.schemas.plan_data_request import TaxSettingsRequest
from tests.engine_support import hsa_row, hsa_state


@pytest.mark.parametrize("year,self_only,family", [(2025, 4300, 8550), (2026, 4400, 8750)])
def test_hsa_applicable_year_and_explicit_family(year, self_only, family):
    assert contribution_room("a", hsa_state([hsa_row()], year), 40) == pytest.approx(self_only)
    assert contribution_room("a", hsa_state([hsa_row(coverage="family")], year), 40) == pytest.approx(family)


def test_marriage_and_unknown_coverage_do_not_establish_family_limit():
    s = hsa_state([])
    assert hsa_contribution_room("a", s, 40) is None
    assert contribution_room("a", s, 40, filing_status="married_filing_jointly") == 4400


def test_ineligible_including_medicare_has_zero_room_without_age_guess():
    assert contribution_room("a", hsa_state([hsa_row(coverage="ineligible")]), 40) == 0
    # Age alone does not establish Medicare enrollment.
    assert contribution_room("a", hsa_state([hsa_row()], ages={"self": 70}), 70) == pytest.approx(5400)


def test_hsa_prorates_eligible_months_and_fixed_catchup():
    s = hsa_state([hsa_row(eligible_months=[1, 2, 3, 4, 5, 6])], ages={"self": 55})
    assert contribution_room("a", s, 55) == pytest.approx((4400 + 1000) / 2)
    s.year = 2027
    s.coverage_inflation_factor = 1.1
    assert contribution_room("a", s, 55) == pytest.approx((4400 * 1.1 + 1000) / 2)


def test_family_base_shared_and_catchups_stay_in_each_owners_hsa():
    s = hsa_state([hsa_row(coverage="family"), hsa_row("spouse", "family")], ages={"self": 55, "spouse": 55})
    s.ytd_contributions = {"a": 9750}
    assert contribution_room("b", s, 55) == pytest.approx(1000)
    assert contribution_room("c", s, 55) == pytest.approx(0)
    s.ytd_contributions["b"] = 1000
    assert contribution_room("b", s, 55) == pytest.approx(0)


def test_family_owner_cannot_use_younger_spouses_catchup():
    s = hsa_state([hsa_row(coverage="family"), hsa_row("spouse", "family")], ages={"self": 55, "spouse": 54})
    s.ytd_contributions = {"a": 9750}
    assert contribution_room("b", s, 54) == pytest.approx(0)


@pytest.mark.parametrize("coverage", [[], [hsa_row("spouse")]])
def test_unknown_spouse_age_cannot_inherit_primary_hsa_catchup(coverage):
    s = hsa_state(coverage, ages={"self": 60})
    assert contribution_room("b", s, 60) == pytest.approx(4400)
    s.owner_ages["spouse"] = 55
    assert contribution_room("b", s, 60) == pytest.approx(5400)


def test_family_shared_limit_does_not_reserve_unknown_spouse_catchup():
    s = hsa_state([hsa_row(coverage="family"), hsa_row("spouse", "family")], ages={"self": 60})
    s.ytd_contributions["a"] = 9750
    assert contribution_room("b", s, 60) == 0


def test_partial_family_configuration_does_not_create_extra_self_only_room():
    s = hsa_state([hsa_row(coverage="family")])
    assert contribution_room("b", s, 40) == 0


def test_independent_self_only_limits_and_month_overlap():
    s = hsa_state([hsa_row(), hsa_row("spouse")])
    s.ytd_contributions = {"a": 4400}
    assert contribution_room("b", s, 40) == pytest.approx(4400)
    s = hsa_state([hsa_row(coverage="family", eligible_months=[1, 2, 3, 4, 5, 6]),
               hsa_row("spouse", eligible_months=[7, 8, 9, 10, 11, 12])])
    s.ytd_contributions = {"a": 4375}
    assert contribution_room("b", s, 40) == pytest.approx(2200)


@pytest.mark.parametrize("explicit_owner,known_account,unknown_account", [
    ("self", "a", "b"), ("spouse", "b", "a"),
])
def test_explicit_self_only_room_is_independent_of_unknown_other_owner(
        explicit_owner, known_account, unknown_account):
    s = hsa_state([hsa_row(explicit_owner)])
    assert contribution_room(known_account, s, 40) == pytest.approx(4400)
    s.ytd_contributions[unknown_account] = 4400
    assert contribution_room(known_account, s, 40) == pytest.approx(4400)
    s.ytd_contributions[known_account] = 2000
    assert contribution_room(known_account, s, 40) == pytest.approx(2400)


@pytest.mark.parametrize("first_account,first_amount,second_account,remaining", [
    ("a", 4375, "b", 2200), ("b", 6575, "a", 0),
])
def test_family_months_share_base_but_other_months_keep_self_only_room(
        first_account, first_amount, second_account, remaining):
    # Jan-Jun both eligible, primary family; Jul-Dec only spouse self-only.
    # Household base: 8750/2 + 4400/2 = 6575, primary own cap 4375.
    s = hsa_state([hsa_row(coverage="family", eligible_months=[1, 2, 3, 4, 5, 6]),
               hsa_row("spouse")])
    assert contribution_room("a", s, 40) == pytest.approx(4375)
    assert contribution_room("b", s, 40) == pytest.approx(6575)
    s.ytd_contributions[first_account] = first_amount
    assert contribution_room(second_account, s, 40) == pytest.approx(remaining)


def test_hsa_employer_and_employee_share_cap_across_accounts():
    s = hsa_state([hsa_row(coverage="family")])
    rules = [PriorityData(priority_rank=1, target_account_id="a", priority_type="income_percent",
                          source_income_id="salary", employee_rate=.04, employer_match_rate=.04)]
    flows = allocate_payroll_contributions(rules, {"salary": 100000}, s, 40)
    assert flows[0].employee_amount == 4000
    assert flows[0].employer_amount == 4000
    assert contribution_room("c", s, 40) == pytest.approx(750)


def payroll(owner="self", code="CA", **kwargs):
    return dict(owner=owner, state_code=code, start_year=2025, **kwargs)


@pytest.mark.parametrize("year,expected", [(2025, 2160), (2026, 2340)])
def test_ca_sdi_official_example_uncapped_wages(year, expected):
    assert state_payroll_obligations(year, {"self": 180000}, [payroll(ca_sdi=True)]) == {"California SDI": expected}
    assert state_payroll_obligations(year, {"self": 360000}, [payroll(ca_sdi=True)])["California SDI"] == expected * 2


def test_wa_cap_is_per_worker_and_cares_is_uncapped():
    rows = [payroll(o, "WA", wa_paid_leave=True, wa_cares=True) for o in ["self", "spouse"]]
    result = state_payroll_obligations(2026, {"self": 250000, "spouse": 150000}, rows)
    assert result["Washington Paid Leave"] == pytest.approx((184500 + 150000) * .0113 * .7143)
    assert result["Washington Cares"] == 2320
    assert sum(state_payroll_obligations(2026, {"self": 250000}, rows).values()) == pytest.approx(2939.208355)


def test_wa_2025_and_future_indexing_not_inflation_of_rates():
    rows = [payroll(code="WA", wa_paid_leave=True, wa_cares=True)]
    assert state_payroll_obligations(2025, {"self": 250000}, rows, 2)["Washington Paid Leave"] == pytest.approx(176100 * .0092 * .7152)
    result = state_payroll_obligations(2027, {"self": 250000}, rows, 1.1)
    assert result["Washington Paid Leave"] == pytest.approx(184500 * 1.1 * .0113 * .7143)
    assert result["Washington Cares"] == 1450


def test_payroll_explicit_coverage_exclusions_and_periods():
    wages = {"self": 180000}
    assert state_payroll_obligations(2026, wages, []) == {}
    assert state_payroll_obligations(2026, wages, [payroll()]) == {}
    assert state_payroll_obligations(2026, {}, [payroll(ca_sdi=True)]) == {"California SDI": 0}
    row = payroll(ca_sdi=True, end_year=2026, employer_pays_fraction=.5)
    assert state_payroll_obligations(2026, wages, [row]) == {"California SDI": 1170}
    assert state_payroll_obligations(2027, wages, [row]) == {}


@pytest.mark.parametrize("schema", [TaxSettings, TaxSettingsRequest])
def test_shared_wire_schema_roundtrip_and_legacy_defaults(schema):
    payload = dict(hsa_coverage=[hsa_row(coverage="family", eligible_months=[1, 2, 3])],
                   state_payroll_coverage=[payroll(ca_sdi=True)])
    settings = schema.model_validate(payload)
    assert schema.model_validate(settings.model_dump()) == settings
    assert schema().hsa_coverage == []
    assert schema().state_payroll_coverage == []
    assert schema().state_payroll_paid_year_to_date == {}
    assert schema().ca_exemption_eligible_owners is None
    assert schema(ca_exemption_eligible_owners=[]).ca_exemption_eligible_owners == []


@pytest.mark.parametrize("schema", [TaxSettings, TaxSettingsRequest])
@pytest.mark.parametrize("payload", [
    {"hsa_coverage": [hsa_row(eligible_months=[0])]},
    {"hsa_coverage": [hsa_row(eligible_months=[13])]},
    {"hsa_coverage": [hsa_row(eligible_months=[1, 1])]},
    {"hsa_coverage": [hsa_row(end_year=2024)]},
    {"hsa_coverage": [hsa_row(), hsa_row(coverage="family")]},
    {"state_payroll_coverage": [payroll(wa_cares=True)]},
    {"state_payroll_coverage": [payroll(employer_pays_fraction=1.1)]},
    {"state_payroll_coverage": [payroll(), payroll()]},
    {"ca_exemption_eligible_owners": ["self", "self"]},
    {"ca_exemption_eligible_owners": ["joint"]},
    {"state_payroll_paid_year_to_date": {"California SDI": -1}},
    {"state_payroll_paid_year_to_date": {"California SDI": float("inf")}},
    {"state_payroll_paid_year_to_date": {"FICA": 1}},
])
def test_invalid_coverage_rejected_on_both_contracts(schema, payload):
    with pytest.raises(ValidationError):
        schema.model_validate(payload)
