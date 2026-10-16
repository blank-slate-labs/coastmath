"""Category suggestions from an operator-configured, OpenAI-compatible model.

Off unless the deployment owner sets ``LEDGER_LLM_ENABLED`` (which also needs
``TRANSACTIONS_ENABLED``), ``LEDGER_LLM_BASE_URL`` and ``LEDGER_LLM_MODEL``.
``LEDGER_LLM_API_KEY`` is optional so local servers work without one;
``LEDGER_LLM_TIMEOUT_SECONDS`` bounds each request. Customers never supply a key.

Requests go to ``{base_url}/chat/completions`` (the OpenAI chat completions
wire format that hosted routers and local servers implement). Each request
carries only what categorization needs: description, merchant, direction, a
whole-unit amount and the raw provider category, keyed by a per-request
number. Account names and numbers, internal IDs and other customers' rows are
never sent. Answers outside the canonical taxonomy are dropped. Prompts and
responses are never logged.
"""
import json
import logging
import os
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlsplit

import httpx

from app.feature_flags import ledger_llm_enabled
from app.ledger.categories import CATEGORIES, UNCATEGORIZED

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 120.0
TEXT_LIMIT = 120
# "uncategorized" is the absence of an answer, never a suggestion.
SUGGESTABLE = tuple(c.id for c in CATEGORIES if c.id != UNCATEGORIZED)
SYSTEM_PROMPT = (
    "You categorize personal bank and card transactions. For each transaction choose exactly one category ID "
    "from this list: " + ", ".join(SUGGESTABLE) + ". "
    "Use transfer for moves between the person's own accounts, debt_payment for loan, mortgage principal or "
    "card payments, saving_investing for contributions to savings or brokerage accounts, and other when "
    "nothing fits. Direction outflow means money left the account; inflow means it arrived. "
    'Reply with JSON only, in the form {"suggestions": [{"ref": "1", "category": "groceries"}]}, '
    "one entry per transaction ref."
)
FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
SAFE_MESSAGES = {
    "timeout": "The suggestion service did not answer in time.",
    "auth": "The suggestion service refused the configured credentials.",
    "rate_limited": "The suggestion service is busy. Try again later.",
    "unavailable": "The suggestion service is unavailable.",
    "malformed": "The suggestion service returned an unreadable answer.",
}


class LlmError(Exception):
    """A provider failure with a user-safe message; never carries payload text."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
        self.message = SAFE_MESSAGES[code]


@dataclass(frozen=True)
class LlmSettings:
    base_url: str
    model: str
    api_key: str | None = None
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def load(cls) -> "LlmSettings | None":
        """The operator's settings, or None when suggestions are not offered."""
        if not ledger_llm_enabled():
            return None
        base_url = os.getenv("LEDGER_LLM_BASE_URL", "").strip().rstrip("/")
        model = os.getenv("LEDGER_LLM_MODEL", "").strip()
        parts = urlsplit(base_url)
        if not model or parts.scheme not in ("http", "https") or not parts.netloc:
            return None
        try:
            timeout = float(os.getenv("LEDGER_LLM_TIMEOUT_SECONDS", "") or DEFAULT_TIMEOUT_SECONDS)
        except ValueError:
            timeout = DEFAULT_TIMEOUT_SECONDS
        timeout = min(max(timeout, 1.0), MAX_TIMEOUT_SECONDS)
        return cls(base_url, model, os.getenv("LEDGER_LLM_API_KEY", "").strip() or None, timeout)


def llm_offered() -> bool:
    return LlmSettings.load() is not None


@dataclass(frozen=True)
class SuggestionInput:
    """One transaction as the model sees it; ``key`` never leaves the server."""
    key: str
    description: str | None
    merchant: str | None
    amount: Decimal
    provider_category: str | None


def clip(text: str | None) -> str | None:
    text = " ".join((text or "").split())
    return text[:TEXT_LIMIT] or None


def payload_item(ref: str, item: SuggestionInput) -> dict:
    """The only fields sent per transaction."""
    return {
        "ref": ref,
        "description": clip(item.description),
        "merchant": clip(item.merchant),
        "direction": "outflow" if item.amount > 0 else "inflow",
        "amount": int(abs(item.amount).quantize(Decimal(1), rounding=ROUND_HALF_UP)),
        "provider_category": clip(item.provider_category),
    }


def parse_answer(content: object, refs: dict[str, str]) -> dict[str, str]:
    """Map refs back to keys, keeping only canonical, suggestable categories."""
    if not isinstance(content, str):
        raise LlmError("malformed")
    match = FENCE.match(content)
    try:
        data = json.loads(match.group(1) if match else content)
    except ValueError as error:
        raise LlmError("malformed") from error
    entries = data.get("suggestions") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise LlmError("malformed")
    result: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ref, category = str(entry.get("ref", "")), entry.get("category")
        if ref in refs and isinstance(category, str) and category.strip() in SUGGESTABLE:
            result.setdefault(refs[ref], category.strip())
    return result


class LedgerLlmClient:
    def __init__(self, settings: LlmSettings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    def suggest(self, items: list[SuggestionInput]) -> dict[str, str]:
        """Suggested canonical category per item key; items without a valid answer are absent."""
        if not items:
            return {}
        refs = {str(index): item.key for index, item in enumerate(items, start=1)}
        body = {
            "model": self.settings.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(
                    {"transactions": [payload_item(ref, item) for ref, item in zip(refs, items, strict=True)]})},
            ],
        }
        headers = {"Authorization": f"Bearer {self.settings.api_key}"} if self.settings.api_key else {}
        try:
            with httpx.Client(timeout=self.settings.timeout, transport=self.transport, follow_redirects=False) as http:
                response = http.post(f"{self.settings.base_url}/chat/completions", json=body, headers=headers)
        except httpx.TimeoutException as error:
            raise LlmError("timeout") from error
        except httpx.HTTPError as error:
            raise LlmError("unavailable") from error
        if response.status_code in (401, 403):
            raise LlmError("auth")
        if response.status_code == 429:
            raise LlmError("rate_limited")
        if response.status_code != 200:
            logger.warning("Ledger suggestion request failed with status %s", response.status_code)
            raise LlmError("unavailable")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise LlmError("malformed") from error
        return parse_answer(content, refs)
