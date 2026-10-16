"""Request and response models for /api/ledger/imports (file imports).

Files travel as base64 in JSON, like the plan importers. Amounts are positive
when money leaves the account.
"""
import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ledger.importers import MAX_FILE_BYTES
from app.schemas.ledger import AccountType, CategoryId, DateRange, LedgerAccountRead

#: Base64 length of the largest accepted file.
MAX_BASE64_LENGTH = 4 * -(-MAX_FILE_BYTES // 3)
#: Distinct raw categories a preview reports and a commit may map.
MAX_CATEGORY_CHOICES = 200


class ImportFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1, max_length=MAX_BASE64_LENGTH)


class ImportPreviewRequest(ImportFile):
    # An existing file account to count rows already stored.
    source_id: uuid.UUID | None = None
    # CSV only: read with this mapping instead of the suggested one.
    mapping: dict[str, Any] | None = None


class NewFileAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    account_type: AccountType
    subtype: str | None = Field(default=None, max_length=60)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    institution_name: str | None = Field(default=None, min_length=1, max_length=255)


class CategoryChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(min_length=1, max_length=100)
    category: CategoryId


class ImportCommitRequest(ImportFile):
    """Exactly one target: an existing file account or a new one."""
    source_id: uuid.UUID | None = None
    new_account: NewFileAccount | None = None
    # CSV: the confirmed mapping and statement period. OFX periods come from the file.
    mapping: dict[str, Any] | None = None
    period: DateRange | None = None
    # OFX: which account section of the file to import.
    statement_index: int | None = Field(default=None, ge=0, le=100)
    categories: list[CategoryChoice] = Field(default_factory=list, max_length=MAX_CATEGORY_CHOICES)

    @model_validator(mode="after")
    def one_target(self):
        if (self.source_id is None) == (self.new_account is None):
            raise ValueError("Choose an existing account or describe a new one")
        return self


class PreviewRow(BaseModel):
    date: date
    amount: float
    description: str
    merchant_name: str | None
    category: str | None
    status: str
    currency: str | None


class RowIssueRead(BaseModel):
    row: int
    reason: str


class CsvColumnRead(BaseModel):
    index: int
    name: str
    suggested_role: str


class DateFormatRead(BaseModel):
    format: str
    label: str
    matches: int
    date_from: date
    date_to: date


class SignRead(BaseModel):
    convention: Literal["inflows_positive", "inflows_negative"]
    confidence: Literal["high", "medium", "low"]
    basis: Literal["keywords", "majority", "default"]


class CsvDetailsRead(BaseModel):
    encoding: str
    delimiter: str
    header_row: int | None
    data_start: int
    row_count: int
    columns: list[CsvColumnRead]
    date_formats: list[DateFormatRead]
    date_ambiguous: bool
    decimal_separator: str
    negative_styles: list[str]
    currency_symbols: list[str]
    sign: SignRead | None
    suggested_mapping: dict[str, Any] | None
    sample_rows: list[list[str]]


class ParsedRead(BaseModel):
    """The file read with ``mapping``: sample rows as they would import."""
    rows: list[PreviewRow]
    transaction_count: int
    row_count: int
    issue_count: int
    issues: list[RowIssueRead]
    # Rows identical to an earlier row in the file; each is kept.
    repeated_in_file: int
    date_from: date
    date_to: date
    currencies: list[str]
    # Rows already stored in the target account; null without one.
    existing_count: int | None
    # Rows dated before the preview's ``retention_start``; an import skips them.
    before_retention: int = 0


class ParseErrorRead(BaseModel):
    code: str
    message: str
    field: str | None


class CategoryValueRead(BaseModel):
    value: str
    count: int
    suggested: str | None
    suggested_source: Literal["rule", "alias"] | None


class PeriodRead(BaseModel):
    """A confirmed period contains ``suggested`` and lies within ``earliest``..``latest``."""
    suggested: DateRange
    earliest: date
    latest: date


class OfxStatementRead(BaseModel):
    index: int
    kind: Literal["bank", "credit_card"]
    name: str
    account_type: str
    subtype: str | None
    mask: str | None
    currency: str | None
    institution_name: str | None
    period: DateRange | None
    transaction_count: int
    issue_count: int
    corrections: int
    date_from: date | None
    date_to: date | None
    # A file account imported from this statement before.
    matched_source_id: uuid.UUID | None
    existing_count: int | None
    rows: list[PreviewRow]
    # Rows dated before the preview's ``retention_start``; an import skips them.
    before_retention: int = 0


class ImportPreviewRead(BaseModel):
    format: Literal["csv", "ofx"]
    file_sha256: str
    # A committed import of this same file into the target account.
    previous_import_id: uuid.UUID | None
    csv: CsvDetailsRead | None
    mapping: dict[str, Any] | None
    parsed: ParsedRead | None
    parse_error: ParseErrorRead | None
    categories: list[CategoryValueRead]
    period: PeriodRead | None
    statements: list[OfxStatementRead]
    # The first transaction date an import keeps.
    retention_start: date | None = None


class ImportRead(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    filename: str
    format: str
    date_from: date
    date_to: date
    row_count: int
    imported_count: int
    duplicate_count: int
    skipped_count: int
    status: Literal["committed", "reverted"]
    created_at: datetime
    reverted_at: datetime | None
    # Rows this import owns now; reverting removes or reassigns them.
    transaction_count: int
    # This import created its account and nothing else is stored there, so a
    # revert with ``remove_account=true`` removes the account too.
    revert_removes_account: bool = False


class ImportCommitRead(BaseModel):
    import_: ImportRead = Field(alias="import", serialization_alias="import")
    account: LedgerAccountRead
    created_account: bool
    inserted: int
    existing: int
    skipped: int
    removed: int
    rules_saved: int
    # Rows dated before ``retention_start``, included in ``skipped``.
    before_retention: int = 0
    retention_start: date | None = None

    model_config = ConfigDict(populate_by_name=True)


class ImportRevertRead(BaseModel):
    import_: ImportRead = Field(alias="import", serialization_alias="import")
    removed: int
    reassigned: int
    # The revert also removed the account the import created (``remove_account=true``).
    account_removed: bool = False

    model_config = ConfigDict(populate_by_name=True)
