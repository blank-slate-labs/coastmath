"""Corrected persona fixtures (tests/fixtures/corrected): loading, the engine
request they map to, and saving one as a plan through the ORM."""
import json
import uuid
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from app.models import Plan
from app.routers.helpers import load_plan_data
from coastmath.schemas.plan_data_request import PlanDataRequest

FIXTURES = Path(__file__).parent / "fixtures" / "corrected"


def corrected_fixture(case):
    return json.loads((FIXTURES / f"{case}.json").read_text())


def engine_request(plan):
    """Engine fractions -> the existing percent-based API contract."""
    raw = asdict(plan)
    for income in raw["income_streams"]:
        for key in ("growth_rate", "withholding_percent"):
            income[key] *= 100
    for expense in raw["expenses"]:
        for key in ("growth_rate", "recurrence_growth_rate"):
            if expense[key] is not None:
                expense[key] *= 100
    return PlanDataRequest.model_validate(raw)


def construct(model_class, raw):
    """Materialize fixture columns only; let ORM defaults apply on flush."""
    fields = {}
    for column in model_class.__table__.columns:
        if column.name not in raw:
            continue
        value = raw[column.name]
        if value is not None:
            try:
                value_type = column.type.python_type
            except NotImplementedError:
                value_type = None
            if value_type is uuid.UUID:
                value = uuid.UUID(str(value))
            elif value_type is date and isinstance(value, str):
                value = date.fromisoformat(value)
            elif value_type is datetime and isinstance(value, str):
                value = datetime.fromisoformat(value)
        fields[column.name] = value
    return model_class(**fields)


def persist_fixture(raw, db_session, test_user):
    adjusted = deepcopy(raw)
    adjusted["user_id"] = str(test_user.id)
    adjusted["snapshot_conditions"] = {a["id"]: a for a in raw["accounts"]}
    model = construct(Plan, adjusted)
    for relation in Plan.__mapper__.relationships:
        if relation.key in ("user", "baseline_plan") or not raw.get(relation.key):
            continue
        values = deepcopy(raw[relation.key])
        if relation.uselist:
            for value in values:
                if relation.key in ("income_streams", "expenses"):
                    for key in ("growth_rate", "recurrence_growth_rate", "withholding_percent"):
                        if value.get(key) is not None:
                            value[key] *= 100
            setattr(model, relation.key, [construct(relation.mapper.class_, value) for value in values])
        else:
            setattr(model, relation.key, construct(relation.mapper.class_, values))
    db_session.add(model)
    db_session.commit()
    db_session.expire_all()
    return load_plan_data(model.id, test_user, db_session, today=date(2026, 9, 8))
