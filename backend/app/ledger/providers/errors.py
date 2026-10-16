"""Typed provider errors whose messages are safe to show and to log.

Messages never quote URLs, credentials, amounts, descriptions or a provider's
own error text. ``code`` is a stable identifier the sync layer and the API
error envelope can carry; ``status`` is the HTTP status a route should return.
"""

#: The connection needs the customer: a new token, a new login or a reconnect.
RECONNECT_CODES = frozenset({"PROVIDER_RECONNECT_REQUIRED", "PROVIDER_TOKEN_USED", "PROVIDER_NOT_FOUND"})
#: The same call may succeed later without anyone changing anything.
RETRYABLE_CODES = frozenset({"PROVIDER_RATE_LIMIT", "PROVIDER_UNAVAILABLE"})


class ProviderError(Exception):
    """A provider call failed. ``provider_code`` is the provider's own error code, when it sent one."""

    def __init__(self, code: str, message: str, status: int = 502, provider_code: str | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.provider_code = code, message, status, provider_code

    @property
    def reconnect_required(self) -> bool:
        return self.code in RECONNECT_CODES

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_CODES
