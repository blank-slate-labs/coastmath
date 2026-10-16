"""Write-time identity validation; existing read models remain compatible."""
from typing import Annotated

from pydantic import AfterValidator, Field


def require_visible_name(value: str) -> str:
    if not value.strip():
        raise ValueError("Enter a name containing at least one non-space character")
    return value


ItemName = Annotated[str, Field(min_length=1, max_length=255), AfterValidator(require_visible_name)]
