"""Canonical transaction categories and the maps from each provider into them.

Every provider's raw category text stays on the row (``provider_category``);
this module maps it centrally so classification is the same for every
provider. Roles decide treatment:

- spending: counted, as essential or discretionary (flex rules may trim the
  discretionary bucket);
- income: take-home pay (wages, other income) or income the plan models
  elsewhere (interest and dividends, benefits), which is shown but never scales
  wages;
- excluded: never spending, because the plan models it structurally (debts
  have schedules, the engine computes taxes, contributions are savings);
- unclear: an outflow counts as essential, an inflow is shown for review and
  never reduces spending.

Plaid personal finance category names come from Plaid's published taxonomy:
https://plaid.com/documents/transactions-personal-finance-category-taxonomy.csv
"""
import re
from dataclasses import dataclass

from app.ledger import provider_traits


@dataclass(frozen=True)
class Category:
    id: str
    role: str  # spending | income | excluded | unclear
    bucket: str | None  # essential | discretionary | take_home | modeled_elsewhere | None
    kind: str | None  # excluded categories: transfer | debt_payment | saving | taxes
    label: str


def _spend(id: str, bucket: str, label: str) -> Category:
    return Category(id, "spending", bucket, None, label)


CATEGORIES: tuple[Category, ...] = (
    _spend("housing", "essential", "Housing"),
    _spend("home", "essential", "Home"),
    _spend("bills_utilities", "essential", "Bills and utilities"),
    _spend("food_and_drink", "essential", "Food and drink"),
    _spend("groceries", "essential", "Groceries"),
    _spend("transportation", "essential", "Transportation"),
    _spend("health", "essential", "Health"),
    _spend("medical", "essential", "Medical"),
    _spend("insurance", "essential", "Insurance"),
    _spend("education", "essential", "Education"),
    _spend("childcare", "essential", "Childcare"),
    _spend("family", "essential", "Family"),
    _spend("personal_care", "essential", "Personal care"),
    _spend("fees", "essential", "Fees"),
    _spend("dining", "discretionary", "Dining"),
    _spend("entertainment", "discretionary", "Entertainment"),
    _spend("shopping", "discretionary", "Shopping"),
    _spend("travel", "discretionary", "Travel"),
    _spend("gifts_donations", "discretionary", "Gifts and donations"),
    Category("income_wages", "income", "take_home", None, "Wages"),
    Category("income_other", "income", "take_home", None, "Other income"),
    Category("income_interest_dividends", "income", "modeled_elsewhere", None, "Interest and dividends"),
    Category("income_benefits", "income", "modeled_elsewhere", None, "Benefits and pensions"),
    Category("transfer", "excluded", None, "transfer", "Transfer"),
    Category("debt_payment", "excluded", None, "debt_payment", "Debt payment"),
    Category("saving_investing", "excluded", None, "saving", "Saving and investing"),
    Category("taxes", "excluded", None, "taxes", "Taxes"),
    Category("other", "unclear", None, None, "Other"),
    Category("uncategorized", "unclear", None, None, "Uncategorized"),
)
BY_ID: dict[str, Category] = {category.id: category for category in CATEGORIES}
CATEGORY_IDS: tuple[str, ...] = tuple(BY_ID)
UNCATEGORIZED = "uncategorized"
TAKE_HOME = frozenset(c.id for c in CATEGORIES if c.bucket == "take_home")
# Either side of a card payment or own-account transfer may carry one of these.
PAIRABLE = frozenset({"transfer", "debt_payment", "bills_utilities", "saving_investing", "other", "uncategorized"})

PLAID_PRIMARY: dict[str, str] = {
    "INCOME": "income_other",
    "TRANSFER_IN": "transfer",
    "TRANSFER_OUT": "transfer",
    "LOAN_PAYMENTS": "debt_payment",
    "BANK_FEES": "fees",
    "ENTERTAINMENT": "entertainment",
    "FOOD_AND_DRINK": "food_and_drink",
    "GENERAL_MERCHANDISE": "shopping",
    "HOME_IMPROVEMENT": "home",
    "MEDICAL": "medical",
    "PERSONAL_CARE": "personal_care",
    "GENERAL_SERVICES": "bills_utilities",
    "GOVERNMENT_AND_NON_PROFIT": "fees",
    "TRANSPORTATION": "transportation",
    "TRAVEL": "travel",
    "RENT_AND_UTILITIES": "bills_utilities",
}
PLAID_DETAILED: dict[str, str] = {
    "INCOME_DIVIDENDS": "income_interest_dividends",
    "INCOME_INTEREST_EARNED": "income_interest_dividends",
    "INCOME_RETIREMENT_PENSION": "income_benefits",
    "INCOME_UNEMPLOYMENT": "income_benefits",
    "INCOME_TAX_REFUND": "taxes",
    "INCOME_WAGES": "income_wages",
    "INCOME_OTHER_INCOME": "income_other",
    # A cash or check deposit could be anything: an unclear inflow for review.
    "TRANSFER_IN_DEPOSIT": "other",
    "TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS": "saving_investing",
    "TRANSFER_OUT_SAVINGS": "saving_investing",
    "FOOD_AND_DRINK_GROCERIES": "groceries",
    "FOOD_AND_DRINK_RESTAURANT": "dining",
    "FOOD_AND_DRINK_FAST_FOOD": "dining",
    "FOOD_AND_DRINK_COFFEE": "dining",
    "FOOD_AND_DRINK_BEER_WINE_AND_LIQUOR": "dining",
    "FOOD_AND_DRINK_VENDING_MACHINES": "dining",
    "GENERAL_MERCHANDISE_GIFTS_AND_NOVELTIES": "gifts_donations",
    "GENERAL_SERVICES_ACCOUNTING_AND_FINANCIAL_PLANNING": "fees",
    "GENERAL_SERVICES_AUTOMOTIVE": "transportation",
    "GENERAL_SERVICES_CHILDCARE": "childcare",
    "GENERAL_SERVICES_CONSULTING_AND_LEGAL": "fees",
    "GENERAL_SERVICES_EDUCATION": "education",
    "GENERAL_SERVICES_INSURANCE": "insurance",
    "GENERAL_SERVICES_STORAGE": "home",
    "GOVERNMENT_AND_NON_PROFIT_DONATIONS": "gifts_donations",
    "GOVERNMENT_AND_NON_PROFIT_TAX_PAYMENT": "taxes",
    "RENT_AND_UTILITIES_RENT": "housing",
}

# CSV category names, compared after `alias_key` (case, punctuation and plurals ignored).
_ALIASES: dict[str, tuple[str, ...]] = {
    "housing": ("housing", "rent", "rent and mortgage", "property tax and hoa", "hoa"),
    "home": ("home", "home improvement", "household", "furniture", "home maintenance"),
    "bills_utilities": ("bills", "utilities", "bills and utilities", "utility", "phone", "mobile phone", "internet",
                        "cable", "electricity", "gas and electric", "water", "subscriptions", "services"),
    "food_and_drink": ("food", "food and drink", "food and dining"),
    "groceries": ("groceries", "grocery", "supermarket", "supermarkets"),
    "transportation": ("transportation", "transport", "auto", "auto and transport", "car", "gas", "fuel", "parking",
                       "public transit", "public transportation", "rideshare", "taxi", "auto insurance"),
    "health": ("health", "health and fitness", "fitness", "gym"),
    "medical": ("medical", "doctor", "dentist", "pharmacy", "healthcare", "health care"),
    "insurance": ("insurance", "life insurance", "health insurance"),
    "education": ("education", "tuition", "books and supplies", "student"),
    "childcare": ("childcare", "child care", "daycare", "babysitter"),
    "family": ("family", "kids", "children", "pets", "pet", "pet care"),
    "personal_care": ("personal care", "personal", "hair", "beauty", "spa"),
    "fees": ("fees", "fee", "bank fees", "service fee", "atm fee", "fees and charges", "finance charge"),
    "dining": ("dining", "restaurants", "restaurant", "dining out", "fast food", "coffee", "coffee shops", "bars",
               "alcohol and bars"),
    "entertainment": ("entertainment", "movies", "music", "streaming", "hobbies", "recreation"),
    "shopping": ("shopping", "clothing", "electronics", "merchandise", "general merchandise", "amazon"),
    "travel": ("travel", "vacation", "hotel", "lodging", "airfare", "flights", "rental car"),
    "gifts_donations": ("gifts", "gift", "donations", "charity", "gifts and donations", "charitable giving"),
    "income_wages": ("paycheck", "salary", "wages", "payroll", "income wages"),
    "income_other": ("income", "other income", "reimbursement", "bonus"),
    "income_interest_dividends": ("interest", "dividends", "interest income", "dividend income",
                                  "interest and dividends"),
    "income_benefits": ("social security", "pension", "unemployment", "benefits", "retirement income"),
    "transfer": ("transfer", "transfers", "internal transfer", "account transfer"),
    "debt_payment": ("loan", "loan payment", "loans", "mortgage", "mortgage payment", "student loan",
                     "credit card payment", "debt payment", "car payment", "auto payment"),
    "saving_investing": ("savings", "saving", "investments", "investment", "investing", "retirement contribution",
                         "saving and investing", "brokerage"),
    "taxes": ("taxes", "tax", "federal tax", "state tax", "property tax"),
    "other": ("other", "misc", "miscellaneous", "cash", "atm", "cash and atm", "check", "deposit"),
    "uncategorized": ("uncategorized", "unknown", "none"),
}


def alias_key(text: str) -> str:
    """Casefold, read ``&`` as ``and``, drop punctuation and a plural ``s``."""
    words = re.sub(r"[^a-z0-9]+", " ", text.casefold().replace("&", " and ")).split()
    return " ".join(word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word
                    for word in words)


ALIASES: dict[str, str] = {}
for _category, _names in _ALIASES.items():
    for _name in (*_names, _category, BY_ID[_category].label):
        ALIASES.setdefault(alias_key(_name.replace("_", " ")), _category)


def category_for_text(text: str | None) -> str | None:
    """Canonical category for free text such as a CSV category name, or None."""
    if not text or not text.strip():
        return None
    return ALIASES.get(alias_key(text))


def category_for(provider: str, provider_category: str | None) -> str | None:
    """Canonical category for one provider's raw category, or None when unknown."""
    if not provider_category:
        return None
    raw = provider_category.strip()
    traits = provider_traits.traits(provider)
    if traits is not None:
        return traits.categories.get(raw)
    if provider == "plaid":
        upper = raw.upper()
        if upper in PLAID_DETAILED:
            return PLAID_DETAILED[upper]
        if upper in PLAID_PRIMARY:
            return PLAID_PRIMARY[upper]
        # A detailed name Plaid adds later still carries its primary as a prefix.
        prefix = next((primary for primary in sorted(PLAID_PRIMARY, key=len, reverse=True)
                       if upper.startswith(primary + "_")), None)
        return PLAID_PRIMARY[prefix] if prefix else None
    if raw in BY_ID:
        return raw
    return category_for_text(raw)


def category_table() -> list[dict]:
    return [{"id": c.id, "role": c.role, "bucket": c.bucket, "kind": c.kind, "label": c.label} for c in CATEGORIES]
