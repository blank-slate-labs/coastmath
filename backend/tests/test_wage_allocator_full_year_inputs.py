"""Do not silently discard full-year inputs inside the bounded wage allocator."""
import pytest

from coastmath.engine.state_tax_allocation import CAPartYearWageContext
from coastmath.engine.tax_engine import calculate as calculate_tax


@pytest.mark.parametrize('fields,reason', [
    ({'state_income_adjustment': 4000}, 'income adjustments'),
    ({'filing_status': 'head_of_household'}, 'head-of-household'),
    ({'settings': {'ca_dependents_by_year': {'2026': 2}}}, 'dependent-credit'),
    ({'settings': {'ca_dependents_by_year': {2026: 2}}}, 'dependent-credit'),
])
def test_unsupported_part_year_combinations_retain_labeled_full_year_estimate(fields, reason):
    inputs = {'gross_income': 80000, 'deductions': 0, 'filing_status': 'single', 'state_code': 'CA', 'tax_year': 2026, **fields}
    full_year = calculate_tax(**inputs)
    context = CAPartYearWageContext(total_w2_wages=80000, ca_w2_wages=40000,
                                   legacy_residual_in_ca=True, residency_state_codes=('NV', 'CA'))
    result = calculate_tax(**inputs, ca_part_year_context=context)
    assert result.state == full_year.state
    assert any(reason in warning and 'Retained the legacy' in warning for warning in result.state_allocation_diagnostics)


def test_explicit_zero_dependents_keep_supported_wage_allocation():
    inputs = {'gross_income': 80000, 'deductions': 0, 'filing_status': 'single', 'state_code': 'CA', 'tax_year': 2026,
              'settings': {'ca_dependents_by_year': {'2026': 0}}}
    context = CAPartYearWageContext(total_w2_wages=80000, ca_w2_wages=40000,
                                   legacy_residual_in_ca=True, residency_state_codes=('NV', 'CA'))
    result = calculate_tax(**inputs, ca_part_year_context=context)
    assert result.state == pytest.approx(calculate_tax(**inputs).state / 2)
