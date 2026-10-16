"""Scheduled tax-setting changes keyed to a year or a plan milestone."""
from copy import deepcopy

from coastmath.engine.tax_schedule import effective_tax_settings

BASE = {
    "mode": "detailed",
    "ordinary_income_tax_rate": None,
    "taxable_withholding_rate": 0.1,
    "state_brackets": [[10_000, 0.02], [999_999_999, 0.05]],
    "scheduled_changes": [
        {"milestone_id": "retire", "settings": {"mode": "flat", "ordinary_income_tax_rate": 0.15}},
        {"year": 2030, "settings": {"ordinary_income_tax_rate": 0.18}},
        {"year": 2030, "settings": {"ordinary_income_tax_rate": 0.20, "state_brackets": []}},
        {"milestone_id": "missing", "settings": {"mode": "detailed"}},
        {"year": 2020, "settings": {"adjustments": [{"id": "a"}]}},
    ],
}


def test_plans_without_changes_get_the_same_object():
    settings = {"mode": "detailed"}
    assert effective_tax_settings(settings, 2030, {}) is settings
    assert effective_tax_settings(None, 2030, {}) == {}


def test_changes_persist_and_later_entries_win_within_a_year():
    before = deepcopy(BASE)
    reached = {"retire": 2028}
    assert effective_tax_settings(BASE, 2027, reached)["mode"] == "detailed"
    in_2028 = effective_tax_settings(BASE, 2028, reached)
    assert in_2028["mode"] == "flat" and in_2028["ordinary_income_tax_rate"] == 0.15
    in_2031 = effective_tax_settings(BASE, 2031, reached)
    # Both 2030 changes apply in list order; the second clears custom brackets.
    assert in_2031["ordinary_income_tax_rate"] == 0.20
    assert "state_brackets" not in in_2031
    assert in_2031["mode"] == "flat"
    # Settings outside the whitelist and the schedule itself are untouched.
    assert in_2031["taxable_withholding_rate"] == 0.1
    assert "scheduled_changes" not in in_2031
    assert before == BASE


def test_year_order_beats_list_order():
    # The milestone change (listed first) reached in 2032 wins over the 2030 rate.
    result = effective_tax_settings(BASE, 2032, {"retire": 2032})
    assert result["ordinary_income_tax_rate"] == 0.15


def test_missing_or_unreached_milestones_never_apply_and_past_years_already_apply():
    result = effective_tax_settings(BASE, 2026, {})
    assert result["mode"] == "detailed" and result["adjustments"] == [{"id": "a"}]
    result["adjustments"].append({"id": "b"})
    # Results never share mutable values with the plan settings.
    assert BASE["scheduled_changes"][4]["settings"]["adjustments"] == [{"id": "a"}]


def test_milestone_reached_before_the_projection_is_already_in_effect():
    assert effective_tax_settings(BASE, 2026, {"retire": 2019})["mode"] == "flat"
