"""Provider-neutral classification: precedence, kinds, currency and pairing."""
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.ledger.classify import (
    LedgerTxn,
    classify,
    effective_category,
    from_row,
    matched_transfers,
)
from app.ledger.rules import Rule

D = Decimal
DAY = date(2026, 3, 10)


def txn(id, amount, provider_category=None, *, source="card", provider="plaid", day=DAY, status="POSTED",
        currency="USD", override=None, llm=None, description="Synthetic store", merchant=None, excluded=False,
        one_time=False):
    return LedgerTxn(id, source, D(str(amount)), currency, status, day, provider, provider_category, override, llm,
                     description, merchant, excluded, one_time)


def rule(id, pattern, category, *, field="description", match_type="contains", **kwargs):
    return Rule(id, field, match_type, pattern, category, created_at=datetime(2026, 1, 1, tzinfo=UTC),
                **kwargs)


def test_precedence_override_rule_llm_provider_uncategorized():
    rules = [rule("r1", "synthetic", "shopping")]
    base = txn("a", 10, "FOOD_AND_DRINK_GROCERIES", override="travel", llm="dining")
    assert effective_category(base, rules) == ("travel", "override", None)
    assert effective_category(txn("b", 10, "FOOD_AND_DRINK_GROCERIES", llm="dining"), rules) == ("shopping", "rule", "r1")
    assert effective_category(txn("c", 10, "FOOD_AND_DRINK_GROCERIES", llm="dining")) == ("dining", "llm", None)
    assert effective_category(txn("d", 10, "FOOD_AND_DRINK_GROCERIES")) == ("groceries", "provider", None)
    assert effective_category(txn("e", 10, None)) == ("uncategorized", "none", None)
    # Unknown stored values fall through instead of failing.
    assert effective_category(txn("f", 10, None, override="bogus", llm="bogus")) == ("uncategorized", "none", None)
    assert effective_category(txn("g", 10, None), [rule("r2", "synthetic", "bogus")]) == ("uncategorized", "none", None)


def test_kinds_buckets_and_values():
    rows = [
        txn("grocery", 80, "FOOD_AND_DRINK_GROCERIES"),
        txn("dinner", 45, "FOOD_AND_DRINK_RESTAURANT"),
        txn("refund", -20, "GENERAL_MERCHANDISE_CLOTHING_AND_ACCESSORIES"),
        txn("pay", -3000, "INCOME_WAGES", source="checking"),
        txn("interest", -12, "INCOME_INTEREST_EARNED", source="checking"),
        txn("tax", 900, "GOVERNMENT_AND_NON_PROFIT_TAX_PAYMENT", source="checking"),
        txn("deposit", -75, "TRANSFER_IN_DEPOSIT", source="checking"),
        txn("mystery", 30, None),
        txn("pending", 10, "TRAVEL_FLIGHTS", status="PENDING"),
        txn("expired", 10, "TRAVEL_FLIGHTS", status="EXPIRED"),
        txn("euro", 10, "TRAVEL_FLIGHTS", currency="EUR"),
        txn("hidden", 10, "TRAVEL_FLIGHTS", excluded=True),
        txn("sofa", 1500, "HOME_IMPROVEMENT_FURNITURE", one_time=True),
        txn("one_time_pay", -500, "INCOME_OTHER_INCOME", one_time=True, source="checking"),
    ]
    labels = classify(rows)
    assert (labels["grocery"].kind, labels["grocery"].bucket, labels["grocery"].value) == ("spending", "essential", 80)
    assert labels["dinner"].bucket == "discretionary"
    assert (labels["refund"].kind, labels["refund"].value) == ("refund", -20)
    assert (labels["pay"].kind, labels["pay"].bucket, labels["pay"].value) == ("income", "take_home", 3000)
    assert labels["interest"].bucket == "modeled_elsewhere"
    assert labels["tax"].kind == "taxes" and labels["tax"].value == 900
    assert labels["deposit"].kind == "other_deposit" and labels["deposit"].value == 75
    assert labels["mystery"].kind == "spending" and labels["mystery"].bucket == "essential"
    assert labels["pending"].kind == "pending"
    assert labels["expired"].kind == "unsupported" and labels["euro"].kind == "unsupported"
    assert labels["hidden"].kind == "excluded"
    assert (labels["sofa"].kind, labels["sofa"].bucket, labels["sofa"].value) == ("one_time", "essential", 1500)
    assert labels["one_time_pay"].kind == "one_time" and labels["one_time_pay"].bucket is None


def test_currency_is_a_parameter():
    rows = [txn("euro", 10, "TRAVEL_FLIGHTS", currency="EUR"), txn("usd", 10, "TRAVEL_FLIGHTS")]
    labels = classify(rows, currency="EUR")
    assert labels["euro"].kind == "spending" and labels["usd"].kind == "unsupported"


def test_card_payment_pairs_across_sources_over_canonical_pairable_categories():
    rows = [
        txn("out", 500, "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT", source="checking", day=date(2026, 3, 1)),
        txn("in", -500, "TRANSFER_IN_ACCOUNT_TRANSFER", source="card", day=date(2026, 3, 3)),
        txn("far", -500, None, source="savings", day=date(2026, 3, 9)),
        # Groceries are never pairable; an equal refund elsewhere stays a refund.
        txn("food", 60, "FOOD_AND_DRINK_GROCERIES", source="checking", day=date(2026, 3, 1)),
        txn("food_back", -60, "FOOD_AND_DRINK_GROCERIES", source="card", day=date(2026, 3, 1)),
        # Same account never pairs; one-time and excluded rows never pair.
        txn("same_out", 40, None, source="card", day=date(2026, 3, 1)),
        txn("same_in", -40, None, source="card", day=date(2026, 3, 1)),
        txn("flag_out", 70, None, source="checking", one_time=True),
        txn("flag_in", -70, None, source="card"),
    ]
    labels = classify(rows)
    assert labels["out"].kind == labels["in"].kind == "transfer" and labels["out"].value == 500
    assert labels["far"].kind == "other_deposit"
    assert labels["food"].kind == "spending" and labels["food_back"].kind == "refund"
    assert labels["same_out"].kind == "spending" and labels["same_in"].kind == "other_deposit"
    assert labels["flag_in"].kind == "other_deposit"
    categories = {row.id: effective_category(row)[0] for row in rows}
    assert matched_transfers(rows, categories) == {"out", "in"}


def test_overrides_and_rules_decide_pairing():
    rows = [
        txn("out", 200, "GENERAL_MERCHANDISE_SUPERSTORES", source="checking"),
        txn("in", -200, None, source="card"),
    ]
    assert classify(rows)["out"].kind == "spending"
    paired = classify(rows, [rule("r", "synthetic", "transfer", direction="outflow")])
    assert paired["out"].kind == "transfer" and paired["out"].source == "rule" and paired["out"].rule_id == "r"


def test_from_row_reads_every_classified_field():
    row = SimpleNamespace(id="1", source_id="2", amount=D("3.50"), currency="USD", status="POSTED",
                          transaction_date=DAY, provider="file", provider_category="Groceries",
                          category_override=None, llm_category="dining", description="d", merchant_name="m",
                          excluded=False, one_time=True)
    record = from_row(row)
    assert record == LedgerTxn("1", "2", D("3.50"), "USD", "POSTED", DAY, "file", "Groceries", None, "dining", "d",
                               "m", False, True)
