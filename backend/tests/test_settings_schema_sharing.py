"""Saved tax and spending settings share the engine request models' fields.

The saved models subclass the request models and differ only in their name,
in rejecting unknown spending-rule keys, and in omitting unset
``estimated_payments`` and ``tax_target`` when serialized.
"""
import json

import pytest
from pydantic import ValidationError

from app.schemas.plan import SpendingRules, SpendingRuleThreshold, TaxSettings
from coastmath.schemas.plan_data_request import (
    SpendingRulesRequest,
    SpendingRuleThresholdRequest,
    TaxSettingsRequest,
)

PAIRS = [
    (TaxSettings, TaxSettingsRequest),
    (SpendingRules, SpendingRulesRequest),
    (SpendingRuleThreshold, SpendingRuleThresholdRequest),
]
# Saved spending rules reject unknown keys; the engine request ignores them.
FORBID_ONLY_SAVED = {SpendingRules, SpendingRuleThreshold}

FULL_TAX = {
    "adjustments": [{"id": "c1", "kind": "credit", "scope": "federal", "amount": 1000, "amount_basis": "nominal",
                     "frequency": "annual"}],
    "scheduled_changes": [{"year": 2027, "settings": {"state_brackets": [[1e12, 0.05]]}}],
    "state_deduction_rules": True,
    "federal_brackets": [[20000, 0.1], [1e12, 0.2]],
    "federal_standard_deduction": 15000,
    "federal_overrides_indexed": False,
    "rmd_start_ages": {"self": 75},
    "state_payroll_wages_year_to_date": {"self": 1000},
    "ca_dependents_by_year": {2026: 1},
    "oh_dependents_by_year": {2026: 2},
    "dependent_birth_years": [2015],
    "hsa_coverage": [{"owner": "self", "start_year": 2026, "coverage": "self_only",
                      "eligible_months": list(range(1, 13))}],
    "state_payroll_coverage": [{"owner": "self", "start_year": 2026, "state_code": "CA", "ca_sdi": True,
                                "wa_paid_leave": False}],
    "state_payroll_paid_year_to_date": {"California SDI": 100},
    "ca_exemption_eligible_owners": ["self"],
    "oh_exemption_eligible_owners": ["self"],
    "mode": "flat",
    "ordinary_income_tax_rate": 0.2,
    "capital_gains_tax_rate": 0.1,
    "taxable_withholding_rate": 0.1,
    "tax_deferred_withholding_rate": 0.2,
    "settlement_lag_years": 1,
    "cash_flow_frequency": "annual",
    "withdrawal_cash_flow_frequency": "monthly",
    "state_brackets": [[1e12, 0.05]],
    "year_to_date": {"tax_year": 2026, "gross_income": 60000},
    "capital_loss_carryforward": 3000,
    "mfs_lived_apart_all_year": True,
    "estimated_payments": {"strategy": "safe_harbor", "prior_year_total_tax": 5},
    "tax_target": {"kind": "federal_bracket", "bracket_rate": 0.12},
    "blend_drawdown_to_tax_target": True,
    "asset_location": {"bond_allocation_mode": "household"},
    "medical_expense_deductions": True,
    "state_529_deduction": True,
}
FULL_SPENDING = {
    "flex_threshold": -0.05,
    "flex_reduction": 0.3,
    "lookback_years": 2,
    "spending_floor": 0.5,
    "performance_mode": "all_time_high",
    "interpolation": "linear",
    "thresholds": [{"threshold": -0.1, "reduction": 0.3}],
    "start_milestone_id": "start",
    "end_milestone_id": "end",
    "upside_thresholds": [{"threshold": 0.05, "increase": 0.1}],
    "flex_scope": ["expenses", "strategy_spending"],
    "surplus_mode": "spend_leftover",
}


def _schema(model, mode: str) -> dict:
    """The JSON schema with request model names read as the saved names."""
    text = json.dumps(model.model_json_schema(mode=mode))
    for saved, request in PAIRS:
        text = text.replace(f'"{request.__name__}"', f'"{saved.__name__}"')
        text = text.replace(f'/{request.__name__}"', f'/{saved.__name__}"')
    return json.loads(text)


def _drop_forbid(schema: dict) -> dict:
    """The schema without the ``additionalProperties: false`` of the forbid-only models."""
    names = {model.__name__ for model in FORBID_ONLY_SAVED}
    for node in [schema, *(definition for name, definition in schema.get("$defs", {}).items() if name in names)]:
        if node.get("title") in names:
            assert node.pop("additionalProperties") is False
    return schema


@pytest.mark.parametrize(("saved", "request_model"), PAIRS)
def test_saved_model_subclasses_the_request_model_with_the_same_fields(saved, request_model):
    assert issubclass(saved, request_model)
    assert list(saved.model_fields) == list(request_model.model_fields)
    assert saved.__name__ == request_model.__name__.removesuffix("Request")


@pytest.mark.parametrize("mode", ["validation", "serialization"])
@pytest.mark.parametrize(("saved", "request_model"), PAIRS)
def test_json_schemas_differ_only_in_title_and_extra_handling(saved, request_model, mode):
    saved_schema, request_schema = _schema(saved, mode), _schema(request_model, mode)
    assert _drop_forbid(saved_schema) == request_schema


def test_extra_handling_is_unchanged():
    unknown_threshold = {"threshold": -0.1, "reduction": 0.3, "unknown": 1}
    rejected = [
        (TaxSettings, {"unknown": 1}),
        (TaxSettingsRequest, {"unknown": 1}),
        (SpendingRules, {"unknown": 1}),
        (SpendingRules, {"thresholds": [unknown_threshold]}),
        (SpendingRuleThreshold, unknown_threshold),
    ]
    for model, value in rejected:
        with pytest.raises(ValidationError):
            model.model_validate(value)
    ignored = SpendingRulesRequest.model_validate({"unknown": 1, "thresholds": [unknown_threshold]}).model_dump()
    assert "unknown" not in ignored and "unknown" not in ignored["thresholds"][0]


def test_saved_spending_rules_hold_saved_thresholds():
    rules = SpendingRules.model_validate(FULL_SPENDING)
    assert all(type(item) is SpendingRuleThreshold for item in rules.thresholds)


@pytest.mark.parametrize(("saved", "request_model", "value"), [
    (TaxSettings, TaxSettingsRequest, FULL_TAX),
    (SpendingRules, SpendingRulesRequest, FULL_SPENDING),
])
def test_fully_populated_value_round_trips_through_both_models(saved, request_model, value):
    from_saved, from_request = saved.model_validate(value), request_model.model_validate(value)
    assert from_saved.model_fields_set == set(saved.model_fields)
    assert from_saved.model_dump(mode="json") == from_request.model_dump(mode="json")
    assert request_model.model_validate(from_saved.model_dump()).model_dump(mode="json") == from_saved.model_dump(mode="json")
    assert saved.model_validate(from_request.model_dump()).model_dump(mode="json") == from_request.model_dump(mode="json")


def test_only_saved_tax_settings_omit_unset_estimated_payments_and_target():
    saved, request = TaxSettings().model_dump(), TaxSettingsRequest().model_dump()
    assert not {"estimated_payments", "tax_target"} & set(saved)
    assert request["estimated_payments"] is None and request["tax_target"] is None
    assert {key: value for key, value in request.items() if key not in {"estimated_payments", "tax_target"}} == saved
