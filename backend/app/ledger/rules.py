"""Customer categorization rules: pure matching, evaluated on read.

A rule never rewrites stored rows; classification asks for the best matching
rule each time it runs, so editing or deleting a rule takes effect at once.
Precedence among matching rules: ``equals`` over ``starts_with`` over
``contains``, then the longer pattern, then the newest rule.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

MATCH_FIELDS = ("description", "merchant", "provider_category")
MATCH_TYPES = ("contains", "equals", "starts_with")
DIRECTIONS = ("any", "outflow", "inflow")
_TYPE_RANK = {"equals": 0, "starts_with": 1, "contains": 2}
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def normalize(text: str | None) -> str:
    """Casefold and collapse whitespace; the stored form of every pattern."""
    return " ".join((text or "").casefold().split())


@dataclass(frozen=True)
class Rule:
    id: str
    match_field: str
    match_type: str
    pattern: str
    category: str
    source_id: str | None = None
    direction: str = "any"
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row) -> "Rule":
        return cls(str(row.id), row.match_field, row.match_type, row.pattern, row.category,
                   str(row.source_id) if row.source_id else None, row.direction, row.created_at)


def field_value(match_field: str, description: str | None, merchant: str | None, provider_category: str | None) -> str:
    value = {"description": description, "merchant": merchant, "provider_category": provider_category}[match_field]
    return normalize(value)


def matches(rule: Rule, *, source_id: str, amount: Decimal, description: str | None, merchant: str | None,
            provider_category: str | None) -> bool:
    if rule.source_id is not None and rule.source_id != source_id:
        return False
    if rule.direction == "outflow" and amount <= 0 or rule.direction == "inflow" and amount >= 0:
        return False
    value = field_value(rule.match_field, description, merchant, provider_category)
    if not value or not rule.pattern:
        return False
    if rule.match_type == "equals":
        return value == rule.pattern
    if rule.match_type == "starts_with":
        return value.startswith(rule.pattern)
    return rule.pattern in value


def _precedence(rule: Rule):
    created = rule.created_at or _EPOCH
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (_TYPE_RANK.get(rule.match_type, 3), -len(rule.pattern), -created.timestamp(), rule.id)


def order(rules: list[Rule]) -> list[Rule]:
    """Rules in precedence order: the first match wins."""
    return sorted(rules, key=_precedence)


def best_rule(ordered: list[Rule], **values) -> Rule | None:
    """The first rule of an ``order``-ed list that matches the transaction values."""
    return next((rule for rule in ordered if matches(rule, **values)), None)
