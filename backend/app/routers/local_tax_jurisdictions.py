"""Public catalog of local income tax jurisdictions a residence can select."""
from fastapi import APIRouter, Query
from pydantic import BaseModel

from coastmath.engine.local_tax import catalog_tax_year, list_jurisdictions

router = APIRouter(prefix="/local-tax-jurisdictions", tags=["local tax"])


class LocalTaxComponentRead(BaseModel):
    label: str
    base: str
    kind: str = "tax"


class LocalTaxJurisdictionRead(BaseModel):
    id: str
    name: str
    state_code: str
    components: list[LocalTaxComponentRead]
    # Modeling boundaries also reported as projection warnings.
    limitations: list[str] = []


class LocalTaxCatalogRead(BaseModel):
    tax_year: int
    jurisdictions: list[LocalTaxJurisdictionRead]


@router.get("", response_model=LocalTaxCatalogRead)
def list_local_tax_jurisdictions(
    state_code: str | None = Query(default=None, min_length=2, max_length=2),
) -> LocalTaxCatalogRead:
    """Catalog jurisdictions, optionally for one state.

    A residence may instead select ``{"jurisdiction": "custom"}`` with rates.
    """
    wanted = state_code.upper() if state_code else None
    return LocalTaxCatalogRead(
        tax_year=catalog_tax_year(),
        jurisdictions=[
            LocalTaxJurisdictionRead(
                id=entry["id"], name=entry["name"], state_code=entry["state_code"],
                components=[
                    LocalTaxComponentRead(label=component["label"], base=component.get("base", "per_person"),
                                          kind=component.get("kind", "tax"))
                    for component in entry["components"]
                ],
                limitations=list(entry.get("limitations", ())),
            )
            for entry in list_jurisdictions()
            if wanted is None or entry["state_code"] == wanted
        ],
    )
