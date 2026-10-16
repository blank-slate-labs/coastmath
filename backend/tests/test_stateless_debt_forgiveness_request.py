"""A stateless plan's liability forgiveness follows the stored liability's rules."""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from coastmath.schemas.plan_data_request import (
    DebtForgivenessRequest,
    PlanDataRequest,
    request_to_engine_data,
)


@pytest.mark.parametrize(
    ("match", "fields"),
    [
        ("Choose either a year or a milestone", {}),
        ("Choose either a year or a milestone", {"year": 2030, "milestone_id": "m1"}),
        ("require the declared exclusion treatment", {"year": 2030, "excluded_amount": 1_000}),
        ("require the declared exclusion treatment", {"year": 2030, "exclusion_basis": "insolvency"}),
        ("needs its IRC 108 basis", {"year": 2030, "tax_treatment": "declared_exclusion"}),
    ],
)
def test_invalid_forgiveness_is_rejected(match: str, fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match=match):
        DebtForgivenessRequest(**fields)


def test_forgiveness_reaches_the_engine_liability() -> None:
    request = PlanDataRequest(
        plan_id=uuid.uuid4(),
        birth_year=1980,
        start_year=2026,
        milestones=[{"id": "grad", "name": "Done", "trigger_type": "date", "trigger_date": "2031-06-01"}],
        liabilities=[
            {"id": "loan", "name": "Student loan", "principal_balance": 20_000, "interest_rate": 5,
             "forgiveness": {"year": 2030, "amount": 5_000, "tax_treatment": "declared_exclusion",
                             "excluded_amount": 2_000, "exclusion_basis": "insolvency"}},
            {"id": "pslf", "name": "PSLF loan", "principal_balance": 40_000, "interest_rate": 4,
             "forgiveness": {"milestone_id": "grad"}},
            {"id": "car", "name": "Car", "principal_balance": 8_000, "interest_rate": 6},
        ],
    )
    loan, pslf, car = request_to_engine_data(request).liabilities
    assert (loan.forgiveness.year, loan.forgiveness.amount, loan.forgiveness.excluded_amount) == (2030, 5_000, 2_000)
    assert loan.forgiveness.tax_treatment == "declared_exclusion"
    assert loan.forgiveness.exclusion_basis == "insolvency"
    assert (pslf.forgiveness.milestone_id, pslf.forgiveness.year, pslf.forgiveness.tax_treatment) == (
        "grad", None, "taxable")
    assert car.forgiveness is None
