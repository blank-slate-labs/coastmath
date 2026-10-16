"""Canonical categories: Plaid coverage and free-text aliases."""
import pytest

from app.ledger.categories import (
    BY_ID,
    CATEGORY_IDS,
    PLAID_PRIMARY,
    alias_key,
    category_for,
    category_for_text,
    category_table,
)

# Plaid's detailed personal finance categories, from
# https://plaid.com/documents/transactions-personal-finance-category-taxonomy.csv
PLAID_DETAILED_NAMES = """
INCOME_DIVIDENDS INCOME_INTEREST_EARNED INCOME_RETIREMENT_PENSION INCOME_TAX_REFUND INCOME_UNEMPLOYMENT
INCOME_WAGES INCOME_OTHER_INCOME TRANSFER_IN_CASH_ADVANCES_AND_LOANS TRANSFER_IN_DEPOSIT
TRANSFER_IN_INVESTMENT_AND_RETIREMENT_FUNDS TRANSFER_IN_SAVINGS TRANSFER_IN_ACCOUNT_TRANSFER
TRANSFER_IN_OTHER_TRANSFER_IN TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS TRANSFER_OUT_SAVINGS
TRANSFER_OUT_WITHDRAWAL TRANSFER_OUT_ACCOUNT_TRANSFER TRANSFER_OUT_OTHER_TRANSFER_OUT
LOAN_PAYMENTS_CAR_PAYMENT LOAN_PAYMENTS_CREDIT_CARD_PAYMENT LOAN_PAYMENTS_PERSONAL_LOAN_PAYMENT
LOAN_PAYMENTS_MORTGAGE_PAYMENT LOAN_PAYMENTS_STUDENT_LOAN_PAYMENT LOAN_PAYMENTS_OTHER_PAYMENT
BANK_FEES_ATM_FEES BANK_FEES_FOREIGN_TRANSACTION_FEES BANK_FEES_INSUFFICIENT_FUNDS BANK_FEES_INTEREST_CHARGE
BANK_FEES_OVERDRAFT_FEES BANK_FEES_OTHER_BANK_FEES ENTERTAINMENT_CASINOS_AND_GAMBLING
ENTERTAINMENT_MUSIC_AND_AUDIO ENTERTAINMENT_SPORTING_EVENTS_AMUSEMENT_PARKS_AND_MUSEUMS
ENTERTAINMENT_TV_AND_MOVIES ENTERTAINMENT_VIDEO_GAMES ENTERTAINMENT_OTHER_ENTERTAINMENT
FOOD_AND_DRINK_BEER_WINE_AND_LIQUOR FOOD_AND_DRINK_COFFEE FOOD_AND_DRINK_FAST_FOOD FOOD_AND_DRINK_GROCERIES
FOOD_AND_DRINK_RESTAURANT FOOD_AND_DRINK_VENDING_MACHINES FOOD_AND_DRINK_OTHER_FOOD_AND_DRINK
GENERAL_MERCHANDISE_BOOKSTORES_AND_NEWSSTANDS GENERAL_MERCHANDISE_CLOTHING_AND_ACCESSORIES
GENERAL_MERCHANDISE_CONVENIENCE_STORES GENERAL_MERCHANDISE_DEPARTMENT_STORES
GENERAL_MERCHANDISE_DISCOUNT_STORES GENERAL_MERCHANDISE_ELECTRONICS GENERAL_MERCHANDISE_GIFTS_AND_NOVELTIES
GENERAL_MERCHANDISE_OFFICE_SUPPLIES GENERAL_MERCHANDISE_ONLINE_MARKETPLACES GENERAL_MERCHANDISE_PET_SUPPLIES
GENERAL_MERCHANDISE_SPORTING_GOODS GENERAL_MERCHANDISE_SUPERSTORES GENERAL_MERCHANDISE_TOBACCO_AND_VAPE
GENERAL_MERCHANDISE_OTHER_GENERAL_MERCHANDISE HOME_IMPROVEMENT_FURNITURE HOME_IMPROVEMENT_HARDWARE
HOME_IMPROVEMENT_REPAIR_AND_MAINTENANCE HOME_IMPROVEMENT_SECURITY HOME_IMPROVEMENT_OTHER_HOME_IMPROVEMENT
MEDICAL_DENTAL_CARE MEDICAL_EYE_CARE MEDICAL_NURSING_CARE MEDICAL_PHARMACIES_AND_SUPPLEMENTS
MEDICAL_PRIMARY_CARE MEDICAL_VETERINARY_SERVICES MEDICAL_OTHER_MEDICAL PERSONAL_CARE_GYMS_AND_FITNESS_CENTERS
PERSONAL_CARE_HAIR_AND_BEAUTY PERSONAL_CARE_LAUNDRY_AND_DRY_CLEANING PERSONAL_CARE_OTHER_PERSONAL_CARE
GENERAL_SERVICES_ACCOUNTING_AND_FINANCIAL_PLANNING GENERAL_SERVICES_AUTOMOTIVE GENERAL_SERVICES_CHILDCARE
GENERAL_SERVICES_CONSULTING_AND_LEGAL GENERAL_SERVICES_EDUCATION GENERAL_SERVICES_INSURANCE
GENERAL_SERVICES_POSTAGE_AND_SHIPPING GENERAL_SERVICES_STORAGE GENERAL_SERVICES_OTHER_GENERAL_SERVICES
GOVERNMENT_AND_NON_PROFIT_DONATIONS GOVERNMENT_AND_NON_PROFIT_GOVERNMENT_DEPARTMENTS_AND_AGENCIES
GOVERNMENT_AND_NON_PROFIT_TAX_PAYMENT GOVERNMENT_AND_NON_PROFIT_OTHER_GOVERNMENT_AND_NON_PROFIT
TRANSPORTATION_BIKES_AND_SCOOTERS TRANSPORTATION_GAS TRANSPORTATION_PARKING TRANSPORTATION_PUBLIC_TRANSIT
TRANSPORTATION_TAXIS_AND_RIDE_SHARES TRANSPORTATION_TOLLS TRANSPORTATION_OTHER_TRANSPORTATION TRAVEL_FLIGHTS
TRAVEL_LODGING TRAVEL_RENTAL_CARS TRAVEL_OTHER_TRAVEL RENT_AND_UTILITIES_GAS_AND_ELECTRICITY
RENT_AND_UTILITIES_INTERNET_AND_CABLE RENT_AND_UTILITIES_RENT RENT_AND_UTILITIES_SEWAGE_AND_WASTE_MANAGEMENT
RENT_AND_UTILITIES_TELEPHONE RENT_AND_UTILITIES_WATER RENT_AND_UTILITIES_OTHER_UTILITIES
""".split()


def test_every_plaid_category_maps_detailed_first():
    for name in PLAID_DETAILED_NAMES:
        assert category_for("plaid", name) in BY_ID, name
    for primary in {name.split("_")[0] for name in PLAID_DETAILED_NAMES}:
        assert any(p.startswith(primary) for p in PLAID_PRIMARY)
    for primary in PLAID_PRIMARY:
        assert category_for("plaid", primary) in BY_ID
    notable = {
        "FOOD_AND_DRINK_GROCERIES": "groceries", "FOOD_AND_DRINK_RESTAURANT": "dining",
        "FOOD_AND_DRINK_FAST_FOOD": "dining", "FOOD_AND_DRINK_COFFEE": "dining",
        "FOOD_AND_DRINK_BEER_WINE_AND_LIQUOR": "dining", "RENT_AND_UTILITIES_RENT": "housing",
        "RENT_AND_UTILITIES_WATER": "bills_utilities", "GOVERNMENT_AND_NON_PROFIT_TAX_PAYMENT": "taxes",
        "INCOME_TAX_REFUND": "taxes", "GOVERNMENT_AND_NON_PROFIT_DONATIONS": "gifts_donations",
        "LOAN_PAYMENTS_MORTGAGE_PAYMENT": "debt_payment", "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT": "debt_payment",
        "TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS": "saving_investing", "TRANSFER_OUT_SAVINGS": "saving_investing",
        "TRANSFER_OUT_ACCOUNT_TRANSFER": "transfer", "TRANSFER_IN_SAVINGS": "transfer",
        "TRANSFER_IN_DEPOSIT": "other", "INCOME_WAGES": "income_wages", "INCOME_DIVIDENDS": "income_interest_dividends",
        "INCOME_INTEREST_EARNED": "income_interest_dividends", "INCOME_RETIREMENT_PENSION": "income_benefits",
        "INCOME_UNEMPLOYMENT": "income_benefits", "FOOD_AND_DRINK_OTHER_FOOD_AND_DRINK": "food_and_drink",
    }
    for name, expected in notable.items():
        assert category_for("plaid", name) == expected, name
    # A detailed name added later falls back to its primary; lower case is accepted.
    assert category_for("plaid", "TRAVEL_SPACE_FLIGHTS") == "travel"
    assert category_for("plaid", "food_and_drink_groceries") == "groceries"
    assert category_for("plaid", "NOT_PLAID") is None


@pytest.mark.parametrize("text,expected", [
    ("Groceries", "groceries"), ("GROCERY", "groceries"), ("  dining   out ", "dining"),
    ("Restaurants", "dining"), ("Bills & Utilities", "bills_utilities"), ("Auto & Transport", "transportation"),
    ("Paycheck", "income_wages"), ("Credit Card Payment", "debt_payment"), ("Fees", "fees"), ("fee", "fees"),
    ("Gifts & Donations", "gifts_donations"), ("Interest Income", "income_interest_dividends"),
    ("taxes", "taxes"), ("Tax", "taxes"), ("Personal Care", "personal_care"), ("personal_care", "personal_care"),
    ("Saving and investing", "saving_investing"), ("Deposit", "other"),
])
def test_free_text_aliases_ignore_case_punctuation_and_plurals(text, expected):
    assert category_for_text(text) == expected
    assert category_for("file", text) == expected
    assert category_for("simplefin", text) == expected


def test_unknown_free_text_returns_none():
    assert category_for_text("Quantum widgets") is None
    assert category_for_text("") is None
    assert category_for_text(None) is None
    assert category_for("file", "dining") == "dining"
    assert alias_key("Bills & Utilities!") == "bill and utilitie"
    assert alias_key("Glass") == "glass"


def test_category_table_lists_roles_buckets_and_labels():
    table = {row["id"]: row for row in category_table()}
    assert len(table) == len(CATEGORY_IDS) == 29
    assert table["dining"] == {"id": "dining", "role": "spending", "bucket": "discretionary", "kind": None,
                               "label": "Dining"}
    assert table["saving_investing"]["kind"] == "saving"
    assert table["income_benefits"]["bucket"] == "modeled_elsewhere"
    assert table["uncategorized"]["role"] == "unclear"
