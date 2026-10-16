"""Independent FTB 540 credit and phaseout worksheet expectations."""

import pytest

from coastmath.engine.ca_exemption_credits import ca_exemption_credit
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import calculate
from tests.corrected_fixture_support import (
    corrected_fixture,
    engine_request,
    persist_fixture,
)


@pytest.mark.parametrize("year", [2025, 2026])
@pytest.mark.parametrize(
    "owners,age,spouse_age,status,expected",
    [
        (None, 70, 70, "married_filing_jointly", 0),
        ([], 70, 70, "married_filing_jointly", 0),
        (["self"], 64, None, "single", 153),
        (["self"], 65, None, "single", 306),
        (["self"], None, None, "single", 153),
        (["self", "spouse"], 65, 64, "married_filing_jointly", 459),
        (["self", "spouse"], 65, 65, "married_filing_jointly", 612),
        (["spouse"], 65, 65, "married_filing_jointly", 306),
        (["spouse"], 65, 65, "married_filing_separately", 0),
        (["self", "spouse"], 65, 65, "single", 306),
    ],
)
def test_credit_counts_only_explicit_eligible_owners(
    year, owners, age, spouse_age, status, expected
):
    assert (
        ca_exemption_credit(100000, status, owners, age, spouse_age, year) == expected
    )


@pytest.mark.parametrize(
    "status,threshold,step,count",
    [
        ("single", 252203, 2500, 1),
        ("married_filing_separately", 252203, 1250, 1),
        ("married_filing_jointly", 504411, 2500, 2),
        ("head_of_household", 378310, 2500, 1),
    ],
)
def test_phaseout_threshold_step_and_full_elimination(status, threshold, step, count):
    def credit(agi):
        return ca_exemption_credit(agi, status, ["self", "spouse"], 40, 40)

    assert credit(threshold) == 153 * count
    assert credit(threshold + 0.49) == 153 * count
    assert credit(threshold + 0.50) == 147 * count
    assert credit(threshold + step) == 147 * count
    assert credit(threshold + step + 1) == 141 * count
    assert credit(threshold + step * 25) == 3 * count
    assert credit(threshold + step * 25 + 1) == 0


def test_senior_credit_shares_phaseout_without_duplicate_personal_credit():
    assert ca_exemption_credit(254703, "single", ["self"], 65) == 294
    assert (
        ca_exemption_credit(1e6, "married_filing_jointly", ["self", "spouse"], 70, 70)
        == 0
    )


def test_estimate_year_and_future_inflation_are_explicit():
    assert ca_exemption_credit(0, "single", ["self"], 40, tax_year=2024) == 0
    assert (
        ca_exemption_credit(
            0, "single", ["self"], 40, tax_year=2026, inflation_factor=2
        )
        == 153
    )
    assert (
        ca_exemption_credit(
            0, "single", ["self"], 40, tax_year=2027, inflation_factor=1.03
        )
        == 158
    )


@pytest.mark.parametrize("income,expected", [(0, 0), (10000, 0), (180000, 12494.98)])
def test_credit_is_nonrefundable_and_matches_statutory_tax(income, expected):
    tax = calculate(
        income,
        0,
        "single",
        settings={"ca_exemption_eligible_owners": ["self"]},
        state_code="CA",
        holder_age=32,
        tax_year=2026,
    )
    assert tax.state == pytest.approx(expected, abs=0.01)


def test_other_states_and_custom_brackets_do_not_receive_ca_credit():
    for code, settings in [
        ("NY", {}),
        ("CA", {"state_brackets": [{"min": 0, "max": float("inf"), "rate": 0.1}]}),
    ]:
        baseline = calculate(180000, 0, "single", state_code=code, settings=settings)
        explicit = calculate(
            180000,
            0,
            "single",
            state_code=code,
            settings={**settings, "ca_exemption_eligible_owners": ["self"]},
        )
        assert baseline.state == explicit.state


@pytest.mark.anyio
@pytest.mark.parametrize(
    "owners,expected_credit", [(None, 0), ([], 0), (["self"], 153)]
)
async def test_credit_roundtrips_persisted_and_stateless_http(
    owners, expected_credit, db_session, test_user, client
):
    raw = corrected_fixture("fire_persona")
    raw["life_expectancy"] = 50
    raw["tax_settings"] = {"ca_exemption_eligible_owners": owners}
    persisted = persist_fixture(raw, db_session, test_user)
    request = engine_request(persisted)
    a = await client.post(
        f"/api/plans/{persisted.plan_id}/simulate",
        headers={"X-Client-Date": "2026-09-08"},
    )
    b = await client.post(
        "/api/simulate/stateless", json=request.model_dump(mode="json")
    )
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
    assert a.json()["yearly_snapshots"][0]["state_tax"] == pytest.approx(
        12647.98 - expected_credit, abs=0.01
    )
    # Same input without credit independently reconciles the effect to cash.
    persisted.tax_settings = {"ca_exemption_eligible_owners": []}
    baseline = run_simulation(persisted).yearly_snapshots[0]
    actual = a.json()["yearly_snapshots"][0]
    rate = persisted.assumptions.stock_growth_rate + persisted.assumptions.stock_dividend_yield
    monthly_value = sum((1 + rate) ** (month / 12) for month in range(12)) / 12
    assert actual["net_worth"] - baseline.net_worth == pytest.approx(
        expected_credit * monthly_value, abs=0.01
    )
