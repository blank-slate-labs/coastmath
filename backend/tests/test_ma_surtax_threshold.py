"""Massachusetts 4% surtax threshold is per return, not doubled for joint filers.

Mass. Const. Amend. Art. XLIV, as amended by Art. CXXI
(https://malegislature.gov/Laws/Constitution): "an additional tax of 4 percent
on that portion of annual taxable income in excess of $1,000,000 ... reported on
any return", indexed annually; the 2026 threshold is $1,107,750
(`_sources` in `tax_brackets_2026.json`). The 5% base rate is the same for every
filer, so the schedule is shared across filing statuses. Expected values are
5% x income + 4% x max(0, income - 1,107,750), before the omitted exemption.
"""

import pytest

from coastmath.engine.tax_engine import _calculate_state_tax


@pytest.mark.parametrize("filing_status", [
    "single", "head_of_household", "married_filing_jointly", "married_filing_separately",
])
@pytest.mark.parametrize("taxable_income, expected", [
    (1_000_000, 50_000),
    (1_107_750, 55_387.5),
    (1_500_000, 90_690),     # 75,000 + 0.04 x 392,250
    (2_500_000, 180_690),    # 125,000 + 0.04 x 1,392,250
])
def test_all_filing_statuses_share_surtax_threshold(taxable_income, expected, filing_status):
    assert _calculate_state_tax(taxable_income, "MA", filing_status=filing_status,
                                tax_year=2026) == pytest.approx(expected)


def test_future_year_indexing_scales_threshold_once():
    # Threshold 2 x 1,107,750 = 2,215,500: 0.05 x 3,000,000 + 0.04 x 784,500.
    assert _calculate_state_tax(3_000_000, "MA", filing_status="married_filing_jointly",
                                inflation_factor=2, tax_year=2027) == pytest.approx(181_380)
