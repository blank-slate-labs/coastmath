"""File imports into the provider-neutral ledger: preview, commit, history, revert.

Session-authenticated and scoped to the user's own file accounts. Changes
require TRANSACTIONS_ENABLED; listing, reverting and removing stay available.
Uploads are base64 JSON bounded by ``app.middleware.body_limit``. The logic
lives in ``app.ledger.file_imports``; this module maps it onto HTTP.
"""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error
from app.ledger import file_imports
from app.ledger.accounts import source_label
from app.ledger.environments import active_filter
from app.ledger.file_imports import FileImportError, NewAccount
from app.ledger.gating import require_transactions_enabled
from app.models.financial_connection import FinancialSource, FinancialTransaction
from app.models.ledger import FinancialImport
from app.models.user import User
from app.rate_limit import limiter, session_user
from app.routers.ledger import account_reads, ledger_today, lock_user
from app.schemas.ledger_imports import (
    ImportCommitRead,
    ImportCommitRequest,
    ImportPreviewRead,
    ImportPreviewRequest,
    ImportRead,
    ImportRevertRead,
)

router = APIRouter(prefix="/ledger", tags=["ledger"], dependencies=[Depends(require_transactions_enabled)])


def refuse(error: FileImportError) -> HTTPException:
    return api_error(error.status, error.code, error.message, error.details)


def import_reads(db: Session, records: list[FinancialImport]) -> list[ImportRead]:
    ids = [record.id for record in records]
    counts = dict(db.query(FinancialTransaction.import_id, func.count(FinancialTransaction.id)).filter(
        FinancialTransaction.import_id.in_(ids)).group_by(FinancialTransaction.import_id).all()) if ids else {}
    sources = {source.id: source for source in db.query(FinancialSource).filter(
        FinancialSource.id.in_({record.source_id for record in records})).all()} if ids else {}
    removes = file_imports.reverts_empty_account(db, records)
    return [ImportRead(
        id=record.id, source_id=record.source_id, source_name=source_label(sources[record.source_id]),
        filename=record.filename, format=record.format, date_from=record.date_from, date_to=record.date_to,
        row_count=record.row_count, imported_count=record.imported_count, duplicate_count=record.duplicate_count,
        skipped_count=record.skipped_count, status=record.status, created_at=record.created_at,
        reverted_at=record.reverted_at, transaction_count=counts.get(record.id, 0),
        revert_removes_account=record.id in removes) for record in records]


@router.post("/imports/preview", response_model=ImportPreviewRead)
@limiter.limit("30/minute", key_func=session_user)
def preview_import(request: Request, body: ImportPreviewRequest, current_user: User = Depends(get_current_user),
                   db: Session = Depends(get_db), today: date = Depends(ledger_today)) -> ImportPreviewRead:
    try:
        upload = file_imports.decode_upload(body.content_base64)
        if body.mapping is not None and upload.format != "csv":
            raise FileImportError("VALIDATION_ERROR", "Only CSV files take a column mapping.",
                                  details=[{"field": "mapping", "reason": "csv only"}])
        return ImportPreviewRead(**file_imports.preview_import(
            db, current_user.id, upload, source_id=body.source_id, mapping=body.mapping, today=today))
    except FileImportError as error:
        raise refuse(error) from error


@router.post("/imports", response_model=ImportCommitRead, status_code=201)
@limiter.limit("10/minute", key_func=session_user)
def commit_import(request: Request, body: ImportCommitRequest, current_user: User = Depends(get_current_user),
                  db: Session = Depends(get_db), today: date = Depends(ledger_today)) -> ImportCommitRead:
    lock_user(db, current_user.id)
    try:
        upload = file_imports.decode_upload(body.content_base64)
        result = file_imports.commit_import(
            db, current_user.id, upload, body.filename.replace("\\", "/").rsplit("/", 1)[-1] or "import",
            source_id=body.source_id,
            new_account=NewAccount(**body.new_account.model_dump()) if body.new_account else None,
            mapping=body.mapping, statement_index=body.statement_index,
            period=(body.period.start, body.period.end) if body.period else None,
            categories=[(choice.value, choice.category) for choice in body.categories], today=today)
    except FileImportError as error:
        db.rollback()
        raise refuse(error) from error
    db.commit()
    return ImportCommitRead(
        import_=import_reads(db, [result.record])[0],
        account=account_reads(db, current_user.id, [result.source], today=today)[0],
        created_account=result.created_account, inserted=result.inserted, existing=result.existing,
        skipped=result.skipped, removed=result.removed, rules_saved=result.rules_saved,
        before_retention=result.before_retention, retention_start=result.retention_start)


@router.get("/imports", response_model=list[ImportRead])
def list_imports(source_id: uuid.UUID | None = None, current_user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)) -> list[ImportRead]:
    query = db.query(FinancialImport).join(FinancialSource, FinancialSource.id == FinancialImport.source_id).filter(
        FinancialImport.user_id == current_user.id, active_filter(FinancialSource))
    if source_id is not None:
        query = query.filter(FinancialImport.source_id == source_id)
    return import_reads(db, query.order_by(FinancialImport.created_at.desc(), FinancialImport.id).limit(500).all())


@router.delete("/imports/{import_id}", response_model=ImportRevertRead)
@limiter.limit("30/minute", key_func=session_user)
def revert_import(request: Request, import_id: uuid.UUID, remove_account: bool = False,
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ImportRevertRead:
    """``remove_account=true`` also removes the account when ``revert_removes_account`` says the
    import created it and nothing else is stored there; any other account stays."""
    lock_user(db, current_user.id)
    try:
        record = file_imports.import_for_user(db, current_user.id, import_id)
        removes = remove_account and record.id in file_imports.reverts_empty_account(db, [record])
        result = file_imports.revert_import(db, current_user.id, import_id)
        # Read before the account removal deletes the import record with it.
        read = import_reads(db, [result.record])[0]
        if removes:
            file_imports.delete_file_account(db, current_user.id, result.record.source_id)
    except FileImportError as error:
        db.rollback()
        raise refuse(error) from error
    db.commit()
    return ImportRevertRead(import_=read, removed=result.removed, reassigned=result.reassigned,
                            account_removed=removes)


@router.delete("/accounts/{source_id}", status_code=204)
@limiter.limit("30/minute", key_func=session_user)
def delete_file_account(request: Request, source_id: uuid.UUID, current_user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)) -> Response:
    lock_user(db, current_user.id)
    try:
        file_imports.delete_file_account(db, current_user.id, source_id)
    except FileImportError as error:
        db.rollback()
        raise refuse(error) from error
    db.commit()
    return Response(status_code=204)
