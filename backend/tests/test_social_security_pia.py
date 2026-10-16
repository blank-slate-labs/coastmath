"""Focused coverage for the bounded retired-worker PIA estimate path."""
import datetime

import pytest
from httpx import AsyncClient

from coastmath.engine.social_security import estimate_ss_benefit_from_pia
from coastmath.schemas import birth_year


@pytest.mark.parametrize(
    ("claiming_age", "expected_annual"),
    [(62, 16_800), (67, 24_000), (70, 29_760)],
)
def test_pia_estimate_applies_existing_claiming_factor_once(claiming_age, expected_annual):
    assert estimate_ss_benefit_from_pia(2_000, claiming_age=claiming_age, birth_year=1960) == pytest.approx(expected_annual)


def test_pia_estimate_applies_expected_percentage_after_claiming_factor():
    assert estimate_ss_benefit_from_pia(
        2_000,
        claiming_age=67,
        birth_year=1960,
        expected_benefit_percentage=85,
    ) == pytest.approx(20_400)


def test_pia_estimate_preserves_monthly_precision():
    assert estimate_ss_benefit_from_pia(2_000.25, claiming_age=67, birth_year=1960) == pytest.approx(24_003)


@pytest.mark.anyio
async def test_pia_endpoint_is_additive_and_returns_expected_fraction(client: AsyncClient):
    response = await client.post(
        "/api/plans/ss-estimate",
        json={
            "monthly_pia": 2_000,
            "expected_benefit_percentage": 85,
            "claiming_age": 62,
            "birth_year": 1960,
        },
    )

    assert response.status_code == 200
    assert response.json() == pytest.approx(
        {
            "estimated_annual_benefit": 14_280,
            "claiming_age": 62,
            "claiming_factor": 0.7,
            "full_retirement_age": 67,
            "expected_benefit_percentage": 85,
            "expected_benefit_fraction": 0.85,
        }
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "body",
    [
        {"monthly_pia": -1},
        {"monthly_pia": 2_000, "expected_benefit_percentage": 101},
        {"monthly_pia": 2_000, "claiming_age": 61},
        {"monthly_pia": 2_000, "birth_year": 1899},
        {},
        {"current_annual_income": 50_000, "monthly_pia": 2_000},
        {"current_annual_income": 50_000, "expected_benefit_percentage": 85},
    ],
)
async def test_pia_endpoint_rejects_invalid_or_ambiguous_inputs(client: AsyncClient, body):
    response = await client.post("/api/plans/ss-estimate", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.anyio
async def test_saved_pia_result_round_trips_and_starts_at_claiming_age(client: AsyncClient):
    plan_response = await client.post(
        "/api/plans",
        json={"name": "PIA timing", "birth_year": 1964, "birth_month": 1,
              "plan_type": "FIXED_DATE", "start_date": "2026-09-09"},
    )
    assert plan_response.status_code == 201
    plan_id = plan_response.json()["id"]

    estimated = await client.post(
        "/api/plans/ss-estimate",
        json={"monthly_pia": 2_000, "claiming_age": 67, "birth_year": 1964},
    )
    assert estimated.status_code == 200
    annual_amount = estimated.json()["estimated_annual_benefit"]

    saved = await client.post(
        f"/api/plans/{plan_id}/incomes",
        json={
            "name": "Retired-worker Social Security",
            "annual_amount": annual_amount,
            "growth_rate": 0,
            "tax_category": "social_security",
            "claiming_age": 67,
        },
    )
    assert saved.status_code == 201
    assert saved.json()["annual_amount"] == annual_amount
    assert saved.json()["claiming_age"] == 67

    reloaded = await client.get(f"/api/plans/{plan_id}")
    assert reloaded.status_code == 200
    income = reloaded.json()["income_streams"][0]
    assert income["annual_amount"] == annual_amount
    assert income["claiming_age"] == 67
    assert income["is_social_security"] is True

    simulation = await client.post(f"/api/plans/{plan_id}/simulate")
    assert simulation.status_code == 200
    snapshots = simulation.json()["yearly_snapshots"]
    before_claim = next(s for s in snapshots if s["year"] == 2030)
    claim_year = next(s for s in snapshots if s["year"] == 2031)
    assert not before_claim["cash_flow"]["income_sources"]
    ss_source = next(
        source for source in claim_year["cash_flow"]["income_sources"]
        if source["name"] == "Retired-worker Social Security"
    )
    assert ss_source["amount"] == pytest.approx(annual_amount)


class _NewYearDay(datetime.date):
    """A server clock on 1 January 2028, after the year the limit used to be fixed at."""

    @classmethod
    def today(cls):
        return cls(2028, 1, 1)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("ss-estimate", {"monthly_pia": 2_000, "claiming_age": 67}),
        ("sepp-preview", {"balance": 100_000, "start_age": 50}),
    ],
)
async def test_estimate_birth_year_limit_follows_the_calendar(client: AsyncClient, monkeypatch, path, body):
    monkeypatch.setattr(birth_year, "date", _NewYearDay)

    accepted = await client.post(f"/api/plans/{path}", json={**body, "birth_year": 2028})
    assert accepted.status_code == 200

    refused = await client.post(f"/api/plans/{path}", json={**body, "birth_year": 2029})
    assert refused.status_code == 422
    error = refused.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert [detail["field"] for detail in error["details"]] == ["birth_year"]
