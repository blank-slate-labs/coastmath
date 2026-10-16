from types import SimpleNamespace

import pytest

from app.routers.liabilities import _compute_amortization


def loan(**updates):
    return SimpleNamespace(**({"principal_balance": 10000, "interest_rate": 0, "extra_payment": 0, "monthly_payment": .02, "term_months": None, "payment_type": "percent_of_balance"} | updates))


def test_percentage_payment_tracks_declining_balance():
    rows = _compute_amortization(loan())
    assert rows[0]["remaining_balance"] == pytest.approx(10000 * .98**12, abs=.01)
    assert rows[0]["principal_paid"] == pytest.approx(10000 * (1 - .98**12), abs=.01)


def test_unpaid_interest_increases_debt():
    rows = _compute_amortization(loan(payment_type="fixed", monthly_payment=10, interest_rate=12))
    expected = 10000 * 1.01**12 - 10 * (1.01**12 - 1) / .01
    assert rows[0]["remaining_balance"] == pytest.approx(expected, abs=.01)
    # No principal was paid: the $120 cash payment went entirely to interest.
    assert rows[0]["principal_paid"] == 0
    assert rows[0]["interest_paid"] == pytest.approx(120)


@pytest.mark.parametrize("payment_type", ["fixed", "custom"])
def test_annual_extra_is_spread_over_twelve_months(payment_type):
    # Zero base payment and zero interest isolate the annual-extra cadence.
    rows = _compute_amortization(loan(payment_type=payment_type, monthly_payment=0,
                                      principal_balance=2500, extra_payment=1200))
    assert [r["remaining_balance"] for r in rows] == [1300, 100, 0]
    assert [r["principal_paid"] for r in rows] == [1200, 1200, 100]


def test_percentage_payment_includes_only_one_year_of_extra():
    rows = _compute_amortization(loan(extra_payment=1200))
    expected = 10000 * .98**12 - 100 * (1 - .98**12) / .02
    assert rows[0]["remaining_balance"] == pytest.approx(expected, abs=.005)


@pytest.mark.anyio
async def test_annual_extra_schedule_matches_independent_math_and_both_projections(client):
    plan_response = await client.post("/api/plans", json={
        "name": "Annual extra regression", "birth_year": 1990,
        "plan_type": "FIXED_DATE", "start_date": "2026-01-01",
    })
    assert plan_response.status_code == 201
    plan_id = plan_response.json()["id"]
    url = f"/api/plans/{plan_id}"
    created = await client.post(url + "/liabilities", json={
        "name": "Mortgage", "principal_balance": 240000, "interest_rate": 6,
        "payment_type": "fixed", "monthly_payment": 1438.92,
        "term_months": 360, "extra_payment": 1200,
    })
    assert created.status_code == 201
    liability = created.json()
    response = await client.get(url + f"/liabilities/{liability['id']}/amortization")
    assert response.status_code == 200
    schedule = response.json()["schedule"]

    # Independent monthly recurrence, without application financial helpers.
    balance, cumulative, expected = 240000.0, 0.0, []
    for month in range(1, 601):
        interest = balance * .06 / 12
        payment = min(balance + interest, 1438.92 + 100)
        balance = max(0, balance + interest - payment)
        cumulative += interest
        if month % 12 == 0 or balance == 0:
            expected.append((balance, cumulative))
        if balance == 0:
            break
    assert month == 304
    assert len(schedule) == len(expected) == 26
    for row, (debt, interest) in zip(schedule, expected, strict=True):
        assert row["remaining_balance"] == pytest.approx(debt, abs=.005)
        assert row["cumulative_interest"] == pytest.approx(interest, abs=.005)
    assert schedule[0]["interest_paid"] == 14286.27
    assert schedule[0]["principal_paid"] == 4180.77
    assert schedule[-1]["cumulative_interest"] == 226863.55

    db_result = await client.post(url + "/simulate")
    stateless_result = await client.post("/api/simulate/stateless", json={
        "plan_id": plan_id, "birth_year": 1990, "start_year": 2026,
        "liabilities": [liability],
    })
    for result in (db_result, stateless_result):
        assert result.status_code == 200, result.text
        snapshots = result.json()["yearly_snapshots"]
        # The projection outlives the loan; only the schedule's years are compared.
        for snapshot, (debt, _) in zip(snapshots, expected, strict=False):
            assert snapshot["liabilities_balance"] == pytest.approx(debt, abs=.005)
        assert next(s["year"] for s in snapshots if s["liabilities_balance"] == 0) == 2051
