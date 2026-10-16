"""Tests for the core amortization calculator."""

import pytest

from coastmath.engine.amortization import (
    AmortizationResult,
    AmortizationScheduleRow,
    calculate_fixed_payment,
    calculate_year,
    generate_full_schedule,
)

# ---------------------------------------------------------------------------
# calculate_fixed_payment
# ---------------------------------------------------------------------------

class TestCalculateFixedPayment:
    def test_standard_30yr_mortgage(self):
        # $300,000 at 6% for 30 years → ~$1798.65/month
        payment = calculate_fixed_payment(300_000, 0.06, 360)
        assert abs(payment - 1798.65) < 0.10

    def test_zero_interest_rate(self):
        payment = calculate_fixed_payment(120_000, 0.0, 360)
        assert abs(payment - 333.33) < 0.01

    def test_zero_term(self):
        payment = calculate_fixed_payment(100_000, 0.05, 0)
        assert payment == 0.0

    def test_short_term(self):
        # $10,000 at 5% for 12 months
        payment = calculate_fixed_payment(10_000, 0.05, 12)
        assert payment > 0
        # Total paid should be close to principal + some interest
        total = payment * 12
        assert 10_000 < total < 10_500


# ---------------------------------------------------------------------------
# calculate_year
# ---------------------------------------------------------------------------

class TestCalculateYear:
    def test_basic_fixed_payment(self):
        # $200,000 at 6%, monthly payment ~$1199.10 (30yr)
        monthly = calculate_fixed_payment(200_000, 0.06, 360)
        result = calculate_year(200_000, 0.06, monthly)
        assert isinstance(result, AmortizationResult)
        assert result.remaining_balance < 200_000
        assert result.interest_paid > 0
        assert result.principal_paid > 0
        # Interest + principal should roughly equal total payments
        assert abs(result.interest_paid + result.principal_paid - monthly * 12) < 0.01

    def test_offset_reduces_interest(self):
        monthly = calculate_fixed_payment(200_000, 0.06, 360)
        no_offset = calculate_year(200_000, 0.06, monthly, offset_balance=0)
        with_offset = calculate_year(200_000, 0.06, monthly, offset_balance=50_000)
        # Offset should reduce interest paid
        assert with_offset.interest_paid < no_offset.interest_paid
        # More principal paid with offset (same total payment, less interest)
        assert with_offset.principal_paid > no_offset.principal_paid

    def test_extra_payment(self):
        monthly = calculate_fixed_payment(200_000, 0.06, 360)
        no_extra = calculate_year(200_000, 0.06, monthly)
        with_extra = calculate_year(200_000, 0.06, monthly, extra_payment_annual=12_000)
        # Extra payment reduces remaining balance faster
        assert with_extra.remaining_balance < no_extra.remaining_balance

    def test_percent_of_balance(self):
        # A missing fraction defaults to 2% of the declining balance monthly.
        result = calculate_year(100_000, 0.06, 0, payment_type="percent_of_balance")
        assert result.interest_paid > 0
        assert result.remaining_balance == pytest.approx(100_000 * 0.985 ** 12)

    def test_balance_clamp_final_payment(self):
        # Small balance with large payment — should not go negative
        result = calculate_year(500, 0.06, 1000)
        assert result.remaining_balance == 0.0
        assert result.principal_paid <= 500 + 50  # principal + some interest portion

    def test_zero_balance_input(self):
        result = calculate_year(0, 0.06, 1000)
        assert result.remaining_balance == 0.0
        assert result.interest_paid == 0.0
        assert result.principal_paid == 0.0

    def test_full_offset_zero_interest(self):
        # Offset >= principal: interest should be zero, payments still reduce principal
        monthly = calculate_fixed_payment(100_000, 0.06, 360)
        result = calculate_year(100_000, 0.06, monthly, offset_balance=100_000)
        assert result.interest_paid == 0.0
        assert result.principal_paid > 0
        assert result.remaining_balance < 100_000

    def test_offset_with_extra_payments(self):
        # Offset + extra payments combined should reduce balance faster than either alone
        monthly = calculate_fixed_payment(200_000, 0.06, 360)
        offset_only = calculate_year(200_000, 0.06, monthly, offset_balance=50_000)
        extra_only = calculate_year(200_000, 0.06, monthly, extra_payment_annual=6_000)
        combined = calculate_year(
            200_000, 0.06, monthly, extra_payment_annual=6_000, offset_balance=50_000
        )
        assert combined.remaining_balance < offset_only.remaining_balance
        assert combined.remaining_balance < extra_only.remaining_balance
        assert combined.interest_paid < offset_only.interest_paid

    def test_fractional_active_month_prorates_payment_and_interest(self):
        result = calculate_year(
            principal_balance=95_000,
            annual_rate=0.035,
            monthly_payment=1_200,
            months=3.98,
        )

        assert result.interest_paid + result.principal_paid == pytest.approx(
            1_200 * 3.98,
            abs=0.01,
        )
        assert result.remaining_balance < 95_000

    def test_zero_active_months_leaves_balance_unchanged(self):
        result = calculate_year(95_000, 0.035, 1_200, months=0)

        assert result.remaining_balance == 95_000
        assert result.interest_paid == 0
        assert result.principal_paid == 0


# ---------------------------------------------------------------------------
# generate_full_schedule
# ---------------------------------------------------------------------------

class TestGenerateFullSchedule:
    def test_30yr_mortgage_schedule(self):
        principal = 300_000
        rate = 0.06
        term = 360
        monthly = calculate_fixed_payment(principal, rate, term)
        schedule = generate_full_schedule(principal, rate, term, monthly)
        assert isinstance(schedule, list)
        assert all(isinstance(row, AmortizationScheduleRow) for row in schedule)
        # Should take ~30 years
        assert 29 <= len(schedule) <= 31
        # Final balance should be ~0
        assert schedule[-1].remaining_balance < 1.0
        # Cumulative interest should be reasonable (roughly 2x principal for 6% 30yr)
        assert schedule[-1].cumulative_interest > 200_000
        # Year numbering
        assert schedule[0].year == 1
        assert schedule[-1].year == len(schedule)

    def test_zero_interest_schedule(self):
        principal = 120_000
        term = 120  # 10 years
        monthly = calculate_fixed_payment(principal, 0.0, term)
        schedule = generate_full_schedule(principal, 0.0, term, monthly)
        assert len(schedule) == 10
        assert schedule[-1].remaining_balance < 0.01
        # No interest paid
        assert schedule[-1].cumulative_interest == 0.0

    def test_extra_payment_shortens_term(self):
        principal = 200_000
        rate = 0.05
        term = 360
        monthly = calculate_fixed_payment(principal, rate, term)
        no_extra = generate_full_schedule(principal, rate, term, monthly)
        with_extra = generate_full_schedule(
            principal, rate, term, monthly, extra_payment=12_000
        )
        # Extra payments should shorten the schedule
        assert len(with_extra) < len(no_extra)

    def test_offset_balance(self):
        principal = 200_000
        rate = 0.06
        term = 360
        monthly = calculate_fixed_payment(principal, rate, term)
        no_offset = generate_full_schedule(principal, rate, term, monthly)
        with_offset = generate_full_schedule(
            principal, rate, term, monthly, offset_balance=50_000
        )
        # Offset should reduce total interest and shorten schedule
        assert with_offset[-1].cumulative_interest < no_offset[-1].cumulative_interest
        assert len(with_offset) <= len(no_offset)

    def test_full_offset_schedule(self):
        # Offset >= principal: zero interest every year, loan pays down quickly
        principal = 100_000
        rate = 0.06
        term = 360
        monthly = calculate_fixed_payment(principal, rate, term)
        schedule = generate_full_schedule(
            principal, rate, term, monthly, offset_balance=100_000
        )
        # All interest should be zero
        assert schedule[-1].cumulative_interest == 0.0
        for row in schedule:
            assert row.interest_paid == 0.0
        # Loan should pay off much faster than 30 years (all payment goes to principal)
        assert len(schedule) < 15

    def test_50_year_safety_cap(self):
        # Interest-only payments that never pay down principal
        # Use percent_of_balance which is interest-only
        schedule = generate_full_schedule(
            100_000, 0.06, 360, 0, payment_type="percent_of_balance"
        )
        # Should cap at 50 years
        assert len(schedule) == 50

    def test_months_active_final_year(self):
        # Short loan: $12,000 at 0%, $1000/month = exactly 12 months = 1 year
        schedule = generate_full_schedule(12_000, 0.0, 12, 1000.0)
        assert len(schedule) == 1
        assert schedule[0].months_active == 12

    def test_months_active_partial_final_year(self):
        # $5,000 at 0%, $1000/month = 5 months
        schedule = generate_full_schedule(5_000, 0.0, 5, 1000.0)
        assert len(schedule) == 1
        assert schedule[0].months_active == 5
        assert schedule[0].remaining_balance < 0.01


# ---------------------------------------------------------------------------
# Extra payment edge cases
# ---------------------------------------------------------------------------

class TestExtraPaymentEdgeCases:
    def test_extra_payment_exceeds_remaining_balance(self):
        """Extra payment much larger than balance — should cap, not go negative."""
        # $1,000 balance, $100/month base, $60,000/year extra ($5,000/month)
        result = calculate_year(1_000, 0.06, 100, extra_payment_annual=60_000)
        assert result.remaining_balance == 0.0
        # Total principal paid should not exceed starting balance
        assert result.principal_paid <= 1_000 + 10  # small interest tolerance

    def test_extra_payment_zero_rate(self):
        """0% rate: entire payment (base + extra) goes to principal."""
        result = calculate_year(10_000, 0.0, 500, extra_payment_annual=6_000)
        assert result.interest_paid == 0.0
        # $500 base + $500 extra = $1000/month × 12 = $12,000 > $10,000
        # Should pay off in 10 months
        assert result.remaining_balance == 0.0
        assert result.principal_paid == 10_000

    def test_percent_of_balance_plus_extra(self):
        """percent_of_balance is interest-only; extra goes entirely to principal."""
        # Interest-only base + $12,000/year extra ($1,000/month to principal)
        result = calculate_year(
            100_000, 0.06, 0,
            extra_payment_annual=12_000,
            payment_type="percent_of_balance",
        )
        # Should have paid ~$12,000 in principal (extra) and ~$6,000 interest
        assert result.principal_paid > 11_000
        assert result.interest_paid > 5_000
        assert result.remaining_balance < 100_000 - 11_000

    def test_extra_payment_monthly_distribution(self):
        """Verify extra_payment is split as extra/12 per month."""
        # $12,000/year extra = $1,000/month extra
        # At 0% rate with $0 base payment, each month pays $1,000 principal
        schedule = generate_full_schedule(
            12_000, 0.0, 360, 0.0, extra_payment=12_000
        )
        assert len(schedule) == 1
        assert schedule[0].months_active == 12
        assert schedule[0].remaining_balance < 0.01
        # Exactly $12,000 principal paid ($1,000/month × 12)
        assert abs(schedule[0].principal_paid - 12_000) < 0.01

    def test_extra_payment_early_payoff_months_active(self):
        """Extra payments cause early payoff — months_active reflects partial year."""
        # $6,000 at 0%, $0 base, $12,000/year extra ($1,000/month)
        # Should pay off in 6 months
        schedule = generate_full_schedule(
            6_000, 0.0, 360, 0.0, extra_payment=12_000
        )
        assert len(schedule) == 1
        assert schedule[0].months_active == 6
        assert schedule[0].remaining_balance < 0.01

    def test_extra_payment_final_month_cap(self):
        """Final month payment capped at remaining balance + interest."""
        # $2,500 at 6%, $0 base, $24,000/year extra ($2,000/month)
        # Month 1: interest ~$12.50, principal ~$1987.50, balance ~$512.50
        # Month 2: interest ~$2.56, principal = remaining ~$512.50
        schedule = generate_full_schedule(
            2_500, 0.06, 360, 0.0, extra_payment=24_000
        )
        assert len(schedule) == 1
        assert schedule[0].months_active == 2
        assert schedule[0].remaining_balance == 0.0
        # Total principal must equal starting balance
        assert abs(schedule[0].principal_paid - 2_500) < 0.01


# ---------------------------------------------------------------------------
# 2.6.1 — 30-year mortgage at 6.5% + edge rates
# ---------------------------------------------------------------------------

class TestMortgage65Percent:
    def test_30yr_6_5_percent_payment(self):
        """$300k at 6.5%, 360 months → ~$1,896.20/month."""
        payment = calculate_fixed_payment(300_000, 0.065, 360)
        assert abs(payment - 1896.20) < 0.50

    def test_30yr_6_5_percent_total_interest(self):
        """$300k at 6.5%, 360 months → total interest ~$382,633."""
        principal = 300_000
        monthly = calculate_fixed_payment(principal, 0.065, 360)
        schedule = generate_full_schedule(principal, 0.065, 360, monthly)
        total_interest = schedule[-1].cumulative_interest
        assert abs(total_interest - 382_633) < 1_000
        assert schedule[-1].remaining_balance < 1.0
        assert 29 <= len(schedule) <= 31

    def test_15yr_mortgage(self):
        """15-year mortgage: higher payment, much less total interest."""
        principal = 300_000
        monthly_30 = calculate_fixed_payment(principal, 0.065, 360)
        monthly_15 = calculate_fixed_payment(principal, 0.065, 180)
        # 15yr payment is higher
        assert monthly_15 > monthly_30
        schedule = generate_full_schedule(principal, 0.065, 180, monthly_15)
        assert 14 <= len(schedule) <= 16
        assert schedule[-1].remaining_balance < 1.0
        # Total interest for 15yr should be well under half of 30yr
        assert schedule[-1].cumulative_interest < 200_000

    def test_very_high_rate_20_percent(self):
        """20% rate: payment is affordable but interest dominates."""
        principal = 300_000
        monthly = calculate_fixed_payment(principal, 0.20, 360)
        # Monthly payment should be very high
        assert monthly > 4_000
        schedule = generate_full_schedule(principal, 0.20, 360, monthly)
        assert schedule[-1].remaining_balance < 1.0
        # Total interest massively exceeds principal
        assert schedule[-1].cumulative_interest > principal * 5


# ---------------------------------------------------------------------------
# 2.6.2 — Offset account reduces interest (specific thresholds)
# ---------------------------------------------------------------------------

class TestOffsetThresholds:
    def test_300k_100k_offset_interest_under_75_percent(self):
        """$300k at 6.5% with $100k offset → interest < 75% of no-offset, faster payoff."""
        principal = 300_000
        monthly = calculate_fixed_payment(principal, 0.065, 360)
        no_offset = generate_full_schedule(principal, 0.065, 360, monthly)
        with_offset = generate_full_schedule(
            principal, 0.065, 360, monthly, offset_balance=100_000
        )
        # Interest must be less than 75% of no-offset interest
        assert with_offset[-1].cumulative_interest < 0.75 * no_offset[-1].cumulative_interest
        # Faster payoff
        assert len(with_offset) < len(no_offset)


# ---------------------------------------------------------------------------
# 2.6.4 — Extra payment acceleration (specific thresholds)
# ---------------------------------------------------------------------------

class TestExtraPaymentAcceleration:
    def test_6k_extra_payoff_21_years(self):
        """$300k at 6.5% with $6k/yr extra → payoff ~21 years, interest < 65% of normal."""
        principal = 300_000
        monthly = calculate_fixed_payment(principal, 0.065, 360)
        normal = generate_full_schedule(principal, 0.065, 360, monthly)
        with_extra = generate_full_schedule(
            principal, 0.065, 360, monthly, extra_payment=6_000
        )
        # Payoff significantly faster than 30 years (~18-23 years)
        assert len(with_extra) <= 23
        assert len(with_extra) >= 17
        assert with_extra[-1].remaining_balance < 1.0
        # Interest < 65% of normal
        assert with_extra[-1].cumulative_interest < 0.65 * normal[-1].cumulative_interest

    def test_extra_exceeds_balance_payoff_1_year(self):
        """Extra payment > balance → loan paid off within 1 year."""
        principal = 300_000
        monthly = calculate_fixed_payment(principal, 0.065, 360)
        # Extra payment of $400k/yr dwarfs the balance
        schedule = generate_full_schedule(
            principal, 0.065, 360, monthly, extra_payment=400_000
        )
        assert len(schedule) == 1
        assert schedule[0].remaining_balance < 1.0
