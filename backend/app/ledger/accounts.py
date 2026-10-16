"""Which ledger accounts count toward spending, and how they are named."""
from app.models.financial_connection import FinancialSource

SPENDING_DEPOSITORY_SUBTYPES = {"CHECKING", "CASH_MANAGEMENT", "PREPAID"}
# Providers whose account name and type the customer may edit: nothing
# upstream reports them reliably.
EDITABLE_PROVIDERS = frozenset({"file", "simplefin"})
#: ``account_type`` of an account whose provider reports no type (SimpleFIN)
#: until the customer confirms one. It never feeds spending or balances.
UNCONFIRMED_TYPE = "UNCONFIRMED"


def spending_eligible(source: FinancialSource) -> bool:
    """Accounts people spend from by default: credit cards and checking-like cash."""
    if source.account_type == "CREDIT":
        return source.subtype in {None, "CREDIT_CARD"}
    return source.account_type == "DEPOSITORY" and source.subtype in SPENDING_DEPOSITORY_SUBTYPES


def counts_toward_spending(source: FinancialSource) -> bool:
    """The customer's ``include_in_spending`` choice, else the default."""
    if source.account_type == UNCONFIRMED_TYPE:
        return False
    return source.include_in_spending if source.include_in_spending is not None else spending_eligible(source)


def source_label(source: FinancialSource) -> str:
    name = source.name if source.institution_name.lower() in source.name.lower() else f"{source.institution_name} {source.name}"
    return (name + (f" ··{source.mask}" if source.mask else ""))[:255]
