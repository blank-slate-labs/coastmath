"""Without a plug-in every account has full access; archived plans stay read-only until restored."""
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.access import BANK_LINKING, FULL_ACCESS, ensure_plan_active
from app.models.plan import Plan
from app.models.user import User


def test_full_access_allows_everything_and_reports_no_limits():
    user, active = User(), Plan(name="Active", birth_year=1980)
    archived = Plan(name="Archived", birth_year=1980, archived_at=datetime.now(UTC))
    for action in ("duplicate", "restore_plan"):
        FULL_ACCESS.require(user, action)
    FULL_ACCESS.ensure_plan_openable(archived, user)
    FULL_ACCESS.ensure_within_edit_window(active, user)
    FULL_ACCESS.ensure_can_create_plan(user, None, None)
    assert FULL_ACCESS.edit_window_ends_at(active) is None
    now = datetime.now(UTC)
    assert FULL_ACCESS.plan_editable(active, user, now) and not FULL_ACCESS.plan_editable(archived, user, now)
    plans = [active, archived]
    FULL_ACCESS.present_plans(plans, user, None, start_grace=True)
    assert [plan.editable for plan in plans] == [True, False]
    assert FULL_ACCESS.session_entitlement(user) is None and FULL_ACCESS.session_capabilities(user) == []


def test_an_archived_plan_takes_no_new_data_until_restored():
    archived = Plan(name="Archived", birth_year=1980, archived_at=datetime.now(UTC))
    with pytest.raises(HTTPException) as refused:
        ensure_plan_active(archived, User())
    assert refused.value.status_code == 409
    assert refused.value.detail["error"]["message"] == "Restore this plan before editing it."


def test_full_access_never_limits_provider_linking():
    user = User(is_anonymous=False)
    FULL_ACCESS.require(user, BANK_LINKING)
    assert FULL_ACCESS.allows(user, BANK_LINKING) and FULL_ACCESS.allows(user, "duplicate")
