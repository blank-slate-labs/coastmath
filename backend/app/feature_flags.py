"""Release features require explicit opt-in; credentials do not enable them."""
import os


def transactions_enabled() -> bool:
    """Transaction import and month-by-month spending comparisons.

    Mutating ledger and spending-model routes require it; reads and deletions
    stay available so customers can always see and remove their data.
    """
    return os.getenv("TRANSACTIONS_ENABLED", "").strip().lower() == "true"


def simplefin_enabled() -> bool:
    """SimpleFIN needs no operator credentials: each customer brings a token."""
    return transactions_enabled() and os.getenv("SIMPLEFIN_ENABLED", "").strip().lower() == "true"


def plaid_enabled() -> bool:
    """Plaid also needs PLAID_CLIENT_ID and PLAID_SECRET; keys alone never enable it."""
    return transactions_enabled() and os.getenv("PLAID_ENABLED", "").strip().lower() == "true"


def ledger_llm_enabled() -> bool:
    """Category suggestions send transaction descriptions to the configured model."""
    return transactions_enabled() and os.getenv("LEDGER_LLM_ENABLED", "").strip().lower() == "true"


def stateless_api_enabled() -> bool:
    """Plan-blob engine routes serve tests and local tools; deployed clients never call them."""
    return os.getenv("ENABLE_STATELESS_API", "").strip().lower() == "true"


def api_docs_enabled() -> bool:
    """The OpenAPI schema documents every engine input, so production omits it."""
    return os.getenv("ENABLE_API_DOCS", "").strip().lower() == "true"
