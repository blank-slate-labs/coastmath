"""Birth-year validation evaluated per request, including across New Year."""
from datetime import date
from typing import Annotated

from pydantic import AfterValidator, Field


def validate_birth_year(value: int) -> int:
    if value > date.today().year:
        raise ValueError("Birth year cannot be in the future.")
    return value


BirthYear = Annotated[int, Field(ge=1900), AfterValidator(validate_birth_year)]
