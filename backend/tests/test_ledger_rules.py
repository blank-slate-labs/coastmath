"""Customer rules: normalized matching, filters and precedence."""
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.ledger.rules import Rule, best_rule, matches, normalize, order

OLD = datetime(2026, 1, 1, tzinfo=UTC)
NEW = datetime(2026, 2, 1, tzinfo=UTC)


def values(description="Synthetic Coffee  Shop #12", merchant="Synthetic Coffee", provider_category="FOOD",
           amount="4.50", source_id="card"):
    return dict(source_id=source_id, amount=Decimal(amount), description=description, merchant=merchant,
                provider_category=provider_category)


def test_normalize_casefolds_and_collapses_whitespace():
    assert normalize("  Synthetic\tCOFFEE   shop ") == "synthetic coffee shop"
    assert normalize(None) == ""


def test_match_types_fields_source_and_direction():
    assert matches(Rule("1", "description", "contains", "coffee shop", "dining"), **values())
    assert matches(Rule("1", "description", "starts_with", "synthetic coffee", "dining"), **values())
    assert not matches(Rule("1", "description", "starts_with", "coffee", "dining"), **values())
    assert matches(Rule("1", "merchant", "equals", "synthetic coffee", "dining"), **values())
    assert not matches(Rule("1", "merchant", "equals", "synthetic", "dining"), **values())
    assert matches(Rule("1", "provider_category", "equals", "food", "dining"), **values())
    assert not matches(Rule("1", "merchant", "contains", "coffee", "dining"), **values(merchant=None))
    assert not matches(Rule("1", "description", "contains", "", "dining"), **values())
    assert matches(Rule("1", "description", "contains", "coffee", "dining", source_id="card"), **values())
    assert not matches(Rule("1", "description", "contains", "coffee", "dining", source_id="other"), **values())
    assert matches(Rule("1", "description", "contains", "coffee", "dining", direction="outflow"), **values())
    assert not matches(Rule("1", "description", "contains", "coffee", "dining", direction="inflow"), **values())
    assert matches(Rule("1", "description", "contains", "coffee", "dining", direction="inflow"), **values(amount="-4"))
    assert not matches(Rule("1", "description", "contains", "coffee", "dining", direction="outflow"),
                       **values(amount="-4"))


def test_precedence_equals_then_starts_with_then_contains_then_length_then_newest():
    contains_long = Rule("a", "description", "contains", "synthetic coffee shop", "shopping", created_at=NEW)
    starts = Rule("b", "description", "starts_with", "synthetic", "travel", created_at=OLD)
    equals = Rule("c", "merchant", "equals", "synthetic coffee", "dining", created_at=OLD)
    assert best_rule(order([contains_long, starts, equals]), **values()).id == "c"
    assert best_rule(order([contains_long, starts]), **values()).id == "b"
    short = Rule("d", "description", "contains", "coffee", "groceries", created_at=NEW)
    assert best_rule(order([short, contains_long]), **values()).id == "a"
    older = Rule("e", "description", "contains", "coffee", "health", created_at=OLD)
    naive = Rule("f", "description", "contains", "coffee", "home", created_at=datetime(2025, 1, 1))
    undated = Rule("g", "description", "contains", "coffee", "fees")
    assert [r.id for r in order([undated, naive, older, short])] == ["d", "e", "f", "g"]
    assert best_rule(order([older]), **values(description="Tea")) is None


def test_rule_from_row():
    row = SimpleNamespace(id="1", match_field="merchant", match_type="equals", pattern="x", category="dining",
                          source_id=None, direction="any", created_at=OLD)
    assert Rule.from_row(row) == Rule("1", "merchant", "equals", "x", "dining", None, "any", OLD)
    row.source_id = "s"
    assert Rule.from_row(row).source_id == "s"
