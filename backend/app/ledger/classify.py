"""Classify ledger transactions from every provider (pure, no database).

A positive amount leaves the account and a negative amount arrives
(app/ledger/types.py). Only real consumption counts as spending: money that
moves between the customer's own accounts, debt payments, investing and taxes
is excluded because the plan models those separately; counting them again
would double count the same dollars.

Effective category precedence: the customer's override, then the best
matching rule, then an LLM suggestion, then the provider map, then
uncategorized. ``excluded`` and ``one_time`` are separate customer flags.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import partial

from app.ledger.categories import BY_ID, PAIRABLE, UNCATEGORIZED, category_for
from app.ledger.rules import Rule, best_rule, order

PAIR_DAYS = 4
DEFAULT_CURRENCY = "USD"
# Kinds that are neither spending nor income nor unknown; months total them by kind.
EXCLUDED_KINDS = ("transfer", "debt_payment", "saving", "taxes", "other_deposit", "excluded")


@dataclass(frozen=True)
class LedgerTxn:
    """The provider-neutral fields classification reads from one stored row."""
    id: str
    source_id: str
    amount: Decimal
    currency: str | None
    status: str
    day: date
    provider: str
    provider_category: str | None = None
    override: str | None = None
    llm_category: str | None = None
    description: str | None = None
    merchant: str | None = None
    excluded: bool = False
    one_time: bool = False


@dataclass(frozen=True)
class Classification:
    """``kind`` is spending, refund, income, transfer, debt_payment, saving,
    taxes, other_deposit, one_time, pending, excluded or unsupported. ``value``
    is positive for money spent or received and negative for a refund.
    ``source`` names what decided the category: override, rule, llm, provider
    or none."""
    kind: str
    category: str
    bucket: str | None = None
    value: Decimal = Decimal(0)
    source: str = "none"
    rule_id: str | None = None


def from_row(row) -> LedgerTxn:
    """A ``FinancialTransaction`` row as a classification record."""
    return LedgerTxn(
        id=str(row.id), source_id=str(row.source_id), amount=Decimal(str(row.amount)), currency=row.currency,
        status=row.status, day=row.transaction_date, provider=row.provider, provider_category=row.provider_category,
        override=row.category_override, llm_category=row.llm_category, description=row.description,
        merchant=row.merchant_name, excluded=row.excluded, one_time=row.one_time)


def effective_category(txn: LedgerTxn, ordered_rules: list[Rule] = ()) -> tuple[str, str, str | None]:
    """(canonical category, deciding source, rule ID) for one transaction."""
    if txn.override in BY_ID:
        return txn.override, "override", None
    rule = best_rule(ordered_rules, source_id=txn.source_id, amount=txn.amount, description=txn.description,
                     merchant=txn.merchant, provider_category=txn.provider_category) if ordered_rules else None
    if rule is not None and rule.category in BY_ID:
        return rule.category, "rule", rule.id
    if txn.llm_category in BY_ID:
        return txn.llm_category, "llm", None
    mapped = category_for(txn.provider, txn.provider_category)
    if mapped is not None:
        return mapped, "provider", None
    return UNCATEGORIZED, "none", None


def matched_transfers(txns: list[LedgerTxn], categories: dict[str, str], currency: str = DEFAULT_CURRENCY) -> set[str]:
    """Pair an outflow with an equal inflow in another of the customer's accounts.

    A card payment appears twice: leaving checking and arriving on the card.
    Providers do not always categorize both sides as transfers, so equal and
    opposite amounts within a few days are treated as one internal movement.
    Each transaction pairs at most once, with the closest date.
    """
    usable = [t for t in txns if t.status == "POSTED" and not t.excluded and not t.one_time and t.currency == currency
              and categories[t.id] in PAIRABLE and t.amount != 0]
    inflows: dict[Decimal, list[LedgerTxn]] = defaultdict(list)
    for txn in usable:
        if txn.amount < 0:
            inflows[-txn.amount].append(txn)
    matched: set[str] = set()
    for out in sorted((t for t in usable if t.amount > 0), key=lambda t: (t.day, t.id)):
        candidates = [t for t in inflows.get(out.amount, []) if t.id not in matched and t.source_id != out.source_id
                      and abs((t.day - out.day).days) <= PAIR_DAYS]
        if candidates:
            best = min(candidates, key=lambda t: (abs((t.day - out.day).days), t.id))
            matched.update({out.id, best.id})
    return matched


def _classification(kind: str, bucket: str | None = None, value: Decimal = Decimal(0), *,
                    category: str, source: str, rule_id: str | None) -> Classification:
    return Classification(kind, category, bucket, value, source, rule_id)


def classify(txns: list[LedgerTxn], rules: list[Rule] = (), currency: str = DEFAULT_CURRENCY) -> dict[str, Classification]:
    """Classify every transaction; pass all of the customer's active rows so pairs are found."""
    ordered = order(list(rules))
    decided = {txn.id: effective_category(txn, ordered) for txn in txns}
    categories = {key: value[0] for key, value in decided.items()}
    pairs = matched_transfers(txns, categories, currency)
    result = {}
    for txn in txns:
        category, source, rule_id = decided[txn.id]
        meta = BY_ID[category]
        label = partial(_classification, category=category, source=source, rule_id=rule_id)

        if txn.status == "PENDING":
            result[txn.id] = label("pending")
        elif txn.status != "POSTED" or txn.currency != currency:
            # Expired or shadow rows no longer exist at the institution; other
            # currencies cannot enter the plan without a conversion.
            result[txn.id] = label("unsupported")
        elif txn.excluded:
            result[txn.id] = label("excluded")
        elif txn.one_time:
            # Shown in its month, never extrapolated into a spending model.
            bucket = meta.bucket if meta.role == "spending" else None
            result[txn.id] = label("one_time", bucket, txn.amount)
        elif txn.id in pairs:
            result[txn.id] = label("transfer", value=abs(txn.amount))
        elif meta.role == "income":
            result[txn.id] = label("income", meta.bucket, -txn.amount)
        elif meta.role == "excluded":
            result[txn.id] = label(meta.kind, value=abs(txn.amount))
        elif txn.amount < 0 and meta.role == "unclear":
            # An unexplained credit could be a transfer, reimbursement or refund.
            # It is shown for review but never reduces spending on its own.
            result[txn.id] = label("other_deposit", value=-txn.amount)
        else:
            # An unexplained debit still counts: under-counting spending is the riskier error.
            bucket = meta.bucket if meta.role == "spending" else "essential"
            result[txn.id] = label("refund" if txn.amount < 0 else "spending", bucket, txn.amount)
    return result
