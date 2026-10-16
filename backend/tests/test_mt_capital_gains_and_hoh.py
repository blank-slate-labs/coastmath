"""Montana taxes federal taxable income with filing-status bands and a separate
net long-term capital gains schedule.

MCA 15-30-2101(22): Montana taxable income is federal taxable income adjusted
under 15-30-2120, so the deduction is IRC 63(c) for the filing status (2026:
$16,100 single and MFS, $32,200 joint, $24,150 head of household; Rev. Proc.
2025-32) plus the 63(f) amount per aged individual ($2,050 unmarried, $1,650
married). MCA 15-30-2120(3)(g) and (7): a further $5,500 subtraction per
taxpayer 65 or older, indexed by CPI-U June of the prior year over June 2023
and rounded to $10: 5,500 x 322.561 / 305.109 = 5,814.60 -> $5,810 for 2026.

MCA 15-30-2103 (temporary, through Dec 31, 2026;
https://mca.legmt.gov/bills/mca/title_0150/chapter_0300/part_0210/section_0030/0150-0300-0210-0030.html):
4.7% / 5.65% with the break at $47,500 single and MFS, $71,250 head of
household, $95,000 joint. Net long-term capital gains (IRC 1222, so qualified
dividends are excluded) are the top layer of taxable income and are taxed at
3.0% on the band less nonqualified taxable income and 4.1% above it.
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate


@pytest.mark.parametrize("filing_status, agi, ltcg, expected_taxable, expected_tax", [
    # Control: 100,000 - 16,100 = 83,900
    # 47,500 x 4.7% (2,232.50) + 36,400 x 5.65% (2,056.60) = 4,289.10
    ("single", 100_000, 0, 83_900, 4_289.10),
    # MFS uses the single band and the federal MFS deduction
    ("married_filing_separately", 100_000, 0, 83_900, 4_289.10),
    # 100,000 - 24,150 = 75,850
    # 71,250 x 4.7% (3,348.75) + 4,600 x 5.65% (259.90) = 3,608.65
    ("head_of_household", 100_000, 0, 75_850, 3_608.65),
    # 100,000 - 32,200 = 67,800; nonqualified 27,800 x 4.7% = 1,306.60
    # room 95,000 - 27,800 = 67,200 >= 40,000: 40,000 x 3.0% = 1,200.00
    ("married_filing_jointly", 100_000, 40_000, 67_800, 2_506.60),
    # 150,000 - 16,100 = 133,900; nonqualified 33,900 x 4.7% = 1,593.30
    # room 13,600 x 3.0% = 408.00; 86,400 x 4.1% = 3,542.40
    ("single", 150_000, 100_000, 133_900, 5_543.70),
    # Nonqualified 83,900 exceeds the band: 4,289.10 + 10,000 x 4.1% = 4,699.10
    ("single", 110_000, 10_000, 93_900, 4_699.10),
    # 60,000 - 24,150 = 35,850; nonqualified 15,850 x 4.7% = 744.95
    # room 71,250 - 15,850 = 55,400 >= 20,000: 20,000 x 3.0% = 600.00
    ("head_of_household", 60_000, 20_000, 35_850, 1_344.95),
    # The deduction absorbs ordinary income first; gains above TI are untaxed:
    # 20,000 - 16,100 = 3,900, all gain: 3,900 x 3.0% = 117.00
    ("single", 20_000, 20_000, 3_900, 117.00),
])
def test_mt_schedule(filing_status, agi, ltcg, expected_taxable, expected_tax):
    tax, taxable = _state_tax_and_taxable_income(
        agi, "MT", filing_status=filing_status, tax_year=2026,
        net_long_term_capital_gains=ltcg)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_tax, abs=0.01)


@pytest.mark.parametrize("filing_status, agi, expected_taxable", [
    # 60,000 - (16,100 + 2,050) - 5,810 = 36,040
    ("single", 60_000, 36_040),
    # 120,000 - (32,200 + 2 x 1,650) - 2 x 5,810 = 72,880
    ("married_filing_jointly", 120_000, 72_880),
])
def test_mt_aged_deduction_and_subtraction(filing_status, agi, expected_taxable):
    tax, taxable = _state_tax_and_taxable_income(
        agi, "MT", filing_status=filing_status, holder_age=70, spouse_age=70,
        tax_year=2026)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_taxable * 0.047, abs=0.01)


def test_mt_indexed_bands():
    # Factor 1.1: deduction 17,710, band 52,250. TI 100,000 - 17,710 = 82,290
    # nonqualified 42,290 x 4.7% (1,987.63); room 9,960 x 3.0% (298.80);
    # 30,040 x 4.1% (1,231.64) = 3,518.07
    tax, taxable = _state_tax_and_taxable_income(
        100_000, "MT", filing_status="single", inflation_factor=1.1, tax_year=2026,
        net_long_term_capital_gains=40_000)
    assert taxable == pytest.approx(82_290)
    assert tax == pytest.approx(3_518.07, abs=0.01)


@pytest.mark.parametrize("filing_status, wages, ltcg, expected", [
    ("head_of_household", 100_000, 0, 3_608.65),
    ("married_filing_jointly", 60_000, 40_000, 2_506.60),
    ("single", 50_000, 100_000, 5_543.70),
])
def test_mt_through_calculate(filing_status, wages, ltcg, expected):
    result = calculate(wages, 0, filing_status, state_code="MT", capital_gains=ltcg,
                       earned_income=wages, tax_year=2026, holder_age=50,
                       spouse_age=50 if filing_status == "married_filing_jointly" else None)
    assert result.state == pytest.approx(expected, abs=0.01)


def test_mt_qualified_dividends_are_not_net_long_term_capital_gains():
    # 60,000 - 16,100 = 43,900, all ordinary: 43,900 x 4.7% = 2,063.30
    result = calculate(50_000, 0, "single", state_code="MT", qualified_dividends=10_000,
                       earned_income=50_000, tax_year=2026, holder_age=50)
    assert result.state == pytest.approx(2_063.30, abs=0.01)


def test_mt_loss_carryforward_nets_against_gains():
    # Net LTCG 30,000 - 10,000 = 20,000; TI 70,000 - 16,100 = 53,900
    # nonqualified 33,900 x 4.7% (1,593.30) + room 13,600 x 3.0% (408.00)
    # + 6,400 x 4.1% (262.40) = 2,263.70
    result = calculate(50_000, 0, "single", state_code="MT", capital_gains=30_000,
                       capital_loss_carryforward=10_000, earned_income=50_000,
                       tax_year=2026, holder_age=50)
    assert result.state == pytest.approx(2_263.70, abs=0.01)
