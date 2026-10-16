"""Provider connections for the ledger: offered providers, SimpleFIN, Plaid, sync, disconnect and balance links.

Session-authenticated and scoped to the user's rows, except the Plaid webhook,
which is verified by Plaid's signed JWT instead. Changes require
TRANSACTIONS_ENABLED; reads and deletions stay available. Linking,
reconnecting and manually syncing are the ``bank_linking`` action of the access
policy (``app.access``), which a hosted plug-in may limit. Linking a provider
takes one short request: the credential is claimed and stored encrypted, and
the background worker performs every sync. A plug-in provider that runs its
own connections keeps its own routes.
"""
import logging
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.access import BANK_LINKING, PROVIDER_CREDENTIALS, ensure_plan_active, require
from app.auth.dependencies import get_current_user
from app.clock import aware, utcnow
from app.db import get_db
from app.ledger import connections as lifecycle
from app.ledger import secrets
from app.ledger.accounts import UNCONFIRMED_TYPE
from app.ledger.balances import (
    SUGGESTED_TYPES,
    fail,
    link_source,
    lock_user,
    source_problem,
)
from app.ledger.environments import active_filter, environment_for
from app.ledger.feeds import refresh_feeds
from app.ledger.gating import require_transactions_enabled
from app.ledger.providers import plaid_adapter, plaid_webhooks, simplefin_adapter
from app.ledger.providers.errors import ProviderError
from app.ledger.providers.registry import descriptor, descriptors
from app.models.financial_connection import (
    FinancialBalanceLink,
    FinancialConnection,
    FinancialSource,
)
from app.models.user import User
from app.rate_limit import limiter, session_user
from app.routers.helpers import get_plan_or_404
from app.routers.ledger import account_reads, ledger_today
from app.schemas.ledger_connections import (
    ConnectionAccountRead,
    LedgerConnectionRead,
    LedgerLinkRead,
    LinkBalanceRequest,
    PlaidConnectRequest,
    PlaidLinkTokenRead,
    PlaidLinkTokenRequest,
    PlaidWebhookRead,
    ProviderRead,
    SimpleFINConnectRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ledger", tags=["ledger"], dependencies=[Depends(require_transactions_enabled)])
#: A manual sync soon after a success would spend the customer's daily bridge quota.
MANUAL_SYNC_FLOOR = timedelta(minutes=10)
PLAID_WEBHOOK_PATH = "/api/ledger/webhooks/plaid"


def provider_failure(error: ProviderError) -> None:
    fail(error.message, error.status, error.code)


def neutral_connection(db: Session, user_id: uuid.UUID, connection_id: uuid.UUID) -> FinancialConnection:
    connection = db.query(FinancialConnection).filter(
        FinancialConnection.id == connection_id, FinancialConnection.user_id == user_id,
        FinancialConnection.provider.notin_(lifecycle.self_managed()), active_filter(FinancialConnection)).first()
    if connection is None:
        fail("Connection not found.", 404, "NOT_FOUND")
    return connection


def connection_read(db: Session, connection: FinancialConnection, *, today: date | None = None) -> LedgerConnectionRead:
    sources = sorted(lifecycle.sources_of(db, connection), key=lambda s: (s.institution_name, s.name, str(s.id)))
    links: dict[uuid.UUID, list[FinancialBalanceLink]] = {}
    if sources:
        for link in db.query(FinancialBalanceLink).filter(
                FinancialBalanceLink.source_id.in_([source.id for source in sources])).all():
            links.setdefault(link.source_id, []).append(link)
    reads = account_reads(db, connection.user_id, sources, today=today)
    accounts = [ConnectionAccountRead(
        **read.model_dump(), balance=float(source.balance) if source.balance is not None else None,
        balance_updated_at=source.balance_updated_at, revision=source.revision,
        type_confirmed=source.account_type != UNCONFIRMED_TYPE, blocked_reason=source_problem(source),
        suggested_account_type=SUGGESTED_TYPES.get(source.subtype),
        links=[LedgerLinkRead.model_validate(link) for link in links.get(source.id, [])],
    ) for read, source in zip(reads, sources, strict=True)]
    item = descriptor(connection.provider)
    return LedgerConnectionRead(
        id=connection.id, provider=connection.provider, label=item.label if item else connection.provider,
        institution_name=connection.institution_name, status=connection.status, error=connection.error,
        last_success_at=connection.last_checked_at, next_check_at=connection.next_check_at,
        created_at=connection.created_at, accounts=accounts)


# --- providers and connections ---------------------------------------------------

@router.get("/providers", response_model=list[ProviderRead])
def list_providers(current_user: User = Depends(get_current_user)) -> list[ProviderRead]:
    return [ProviderRead(key=item.key, label=item.label, link_flow=item.link_flow,
                         capabilities=sorted(item.capabilities), offered=item.offered, reason=item.reason,
                         history_days=item.history_days) for item in descriptors()]


@router.get("/connections", response_model=list[LedgerConnectionRead])
def list_connections(current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
                     today: date = Depends(ledger_today)) -> list[LedgerConnectionRead]:
    rows = db.query(FinancialConnection).filter(
        FinancialConnection.user_id == current_user.id, FinancialConnection.disconnected.is_(False),
        FinancialConnection.provider.notin_(lifecycle.self_managed()), active_filter(FinancialConnection),
    ).order_by(FinancialConnection.created_at, FinancialConnection.id).all()
    return [connection_read(db, row, today=today) for row in rows]


def require_linkable(key: str, user: User) -> None:
    item = descriptor(key)
    if item is None or not item.offered:
        fail(item.reason if item and item.reason else "This provider is not offered on this server.", 503,
             "INTEGRATION_UNAVAILABLE")
    require(user, PROVIDER_CREDENTIALS)
    require(user, BANK_LINKING)


@router.post("/connections/simplefin", response_model=LedgerConnectionRead, status_code=201)
@limiter.limit("10/hour", key_func=session_user)
def connect_simplefin(request: Request, body: SimpleFINConnectRequest, response: Response,
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
                      today: date = Depends(ledger_today)) -> LedgerConnectionRead:
    require_linkable("simplefin", current_user)
    if body.connection_id is not None:
        existing = neutral_connection(db, current_user.id, body.connection_id)
        if existing.provider != "simplefin" or existing.disconnected:
            fail("Connection not found.", 404, "NOT_FOUND")
    # The claim is the only provider call here; the worker syncs.
    db.rollback()
    try:
        access_url = simplefin_adapter.make_client().claim(body.setup_token)
    except ProviderError as error:
        provider_failure(error)
    lock_user(db, current_user.id)
    try:
        if body.connection_id is not None:
            connection = neutral_connection(db, current_user.id, body.connection_id)
            if connection.disconnected:
                fail("Connection not found.", 404, "NOT_FOUND")
            lifecycle.replace_credentials(connection, access_url)
            response.status_code = 200
        else:
            connection = lifecycle.create_connection(db, current_user.id, "simplefin", access_url,
                                                     institution_name=simplefin_adapter.DEFAULT_INSTITUTION)
    except secrets.EncryptionUnavailable as error:
        fail(error.message, 503, error.code)
    db.commit()
    return connection_read(db, connection, today=today)


def plaid_connection(db: Session, user_id: uuid.UUID, connection_id: uuid.UUID) -> FinancialConnection:
    connection = neutral_connection(db, user_id, connection_id)
    if connection.provider != "plaid" or connection.disconnected:
        fail("Connection not found.", 404, "NOT_FOUND")
    return connection


def stored_access_token(connection: FinancialConnection) -> str:
    try:
        return secrets.decrypt(connection.credentials_encrypted)
    except secrets.CredentialError:
        fail("This connection's saved access can no longer be read. Disconnect it and connect the institution again.",
             409, "CREDENTIAL_UNAVAILABLE")


@router.post("/connections/plaid/link-token", response_model=PlaidLinkTokenRead)
@limiter.limit("20/hour", key_func=session_user)
def plaid_link_token(request: Request, body: PlaidLinkTokenRequest, current_user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)) -> PlaidLinkTokenRead:
    """A Link token for a new Item, or for update mode on an existing connection."""
    require_linkable("plaid", current_user)
    access_token = None
    if body.connection_id is not None:
        access_token = stored_access_token(plaid_connection(db, current_user.id, body.connection_id))
    db.rollback()
    try:
        # The user's UUID is stable and identifies no one outside CoastMath, as Plaid requires.
        token = plaid_adapter.make_client().create_link_token(str(current_user.id), access_token=access_token)
    except ProviderError as error:
        provider_failure(error)
    return PlaidLinkTokenRead(link_token=token.link_token, expiration=token.expiration)


@router.post("/connections/plaid", response_model=LedgerConnectionRead, status_code=201)
@limiter.limit("10/hour", key_func=session_user)
def connect_plaid(request: Request, body: PlaidConnectRequest, response: Response,
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
                  today: date = Depends(ledger_today)) -> LedgerConnectionRead:
    """Exchange Link's public token for a new connection, or finish update mode on an existing one."""
    require_linkable("plaid", current_user)
    if body.connection_id is not None:
        # Update mode keeps the Item's access token: clear the reconnect state and sync now.
        lock_user(db, current_user.id)
        connection = plaid_connection(db, current_user.id, body.connection_id)
        lifecycle.replace_credentials(connection, stored_access_token(connection))
        db.commit()
        response.status_code = 200
        return connection_read(db, connection, today=today)
    db.rollback()
    client = plaid_adapter.make_client()
    try:
        exchange = client.exchange_public_token(body.public_token)
    except ProviderError as error:
        provider_failure(error)
    lock_user(db, current_user.id)
    existing = db.query(FinancialConnection).filter_by(
        provider="plaid", environment=environment_for("plaid"), provider_connection_id=exchange.item_id).first()
    try:
        if existing is not None and existing.user_id != current_user.id:
            fail("This institution connection already exists.", 409, "CONFLICT")
        if existing is not None:
            # The same Item linked again (or re-linked after a disconnect): keep its accounts and history.
            existing.disconnected = False
            lifecycle.replace_credentials(existing, exchange.access_token)
            connection = existing
            response.status_code = 200
        else:
            connection = lifecycle.create_connection(
                db, current_user.id, "plaid", exchange.access_token, provider_connection_id=exchange.item_id,
                institution_name=body.institution_name or plaid_adapter.DEFAULT_INSTITUTION)
    except (secrets.EncryptionUnavailable, HTTPException) as error:
        db.rollback()
        # Never leave a billed Item behind that no connection can reach.
        try:
            client.remove_item(exchange.access_token)
        except ProviderError as removal:
            logger.warning("Plaid item removal after a refused connection failed: %s.", removal.code)
        if isinstance(error, HTTPException):
            raise
        fail(error.message, 503, error.code)
    db.commit()
    return connection_read(db, connection, today=today)


@router.post("/webhooks/plaid", response_model=PlaidWebhookRead, include_in_schema=False)
@limiter.limit("600/minute")
async def plaid_webhook(request: Request, plaid_verification: str | None = Header(default=None),
                        db: Session = Depends(get_db)) -> PlaidWebhookRead:
    """Unauthenticated by session: the ``Plaid-Verification`` JWT proves Plaid sent this body."""
    item = descriptor("plaid")
    if item is None or not item.offered:
        fail("Plaid is not offered on this server.", 503, "INTEGRATION_UNAVAILABLE")
    body = await request.body()

    def verify_and_handle() -> None:
        try:
            plaid_adapter.make_client().verify_webhook(body, plaid_verification)
        except ProviderError as error:
            logger.warning("Plaid webhook refused: %s.", error.code)
            provider_failure(error)
        plaid_webhooks.handle(db, body)

    # Verification may fetch Plaid's key and the handler uses the database: both block.
    await run_in_threadpool(verify_and_handle)
    return PlaidWebhookRead(received=True)


@router.post("/connections/{connection_id}/sync", response_model=LedgerConnectionRead)
@limiter.limit("20/hour", key_func=session_user)
def sync_connection(connection_id: uuid.UUID, request: Request, current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db), today: date = Depends(ledger_today)) -> LedgerConnectionRead:
    require(current_user, BANK_LINKING)
    lock_user(db, current_user.id)
    connection = neutral_connection(db, current_user.id, connection_id)
    item = descriptor(connection.provider)
    if item is None or not item.offered or not item.pull_sync:
        fail(item.reason if item and item.reason else "This provider cannot sync on this server.", 503,
             "INTEGRATION_UNAVAILABLE")
    if connection.disconnected:
        fail("Connection not found.", 404, "NOT_FOUND")
    if connection.status == lifecycle.RECONNECT_REQUIRED:
        fail("Reconnect this connection before syncing.", 409, "RECONNECT_REQUIRED")
    now = utcnow()
    if not lifecycle.is_syncing(connection, now):
        if connection.last_checked_at and now - aware(connection.last_checked_at) < MANUAL_SYNC_FLOOR:
            fail("This connection synced moments ago. Try again in a few minutes.", 429, "RATE_LIMIT_EXCEEDED")
        lifecycle.schedule_now(connection, now)
        db.commit()
    return connection_read(db, connection, today=today)


@router.delete("/connections/{connection_id}", status_code=204)
def delete_connection(connection_id: uuid.UUID, remove_data: bool = Query(False),
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    lock_user(db, current_user.id)
    connection = neutral_connection(db, current_user.id, connection_id)
    try:
        affected = lifecycle.disconnect(db, connection, remove_data=remove_data, now=utcnow())
    except ProviderError as error:
        db.rollback()
        provider_failure(error)
    refresh_feeds(db, current_user.id, affected)
    db.commit()
    return Response(status_code=204)


# --- balance links ------------------------------------------------------------------

@router.post("/accounts/{source_id}/link", response_model=LedgerLinkRead, status_code=201)
def create_link(source_id: uuid.UUID, body: LinkBalanceRequest, current_user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> LedgerLinkRead:
    ensure_plan_active(get_plan_or_404(body.plan_id, current_user.id, db), current_user)

    def find_source() -> FinancialSource | None:
        source = db.query(FinancialSource).filter(
            FinancialSource.id == source_id, FinancialSource.user_id == current_user.id,
            FinancialSource.provider.notin_(lifecycle.self_managed()), active_filter(FinancialSource)).first()
        item = descriptor(source.provider) if source else None
        return source if item and "balances" in item.capabilities else None

    link = link_source(db, current_user.id, body, find_source, lambda source: lifecycle.is_connected(db, source),
                       utcnow())
    db.commit()
    return LedgerLinkRead.model_validate(link)


@router.delete("/links/{link_id}", status_code=204)
def delete_link(link_id: uuid.UUID, current_user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> Response:
    lock_user(db, current_user.id)
    link = db.query(FinancialBalanceLink).join(FinancialSource, FinancialSource.id == FinancialBalanceLink.source_id).filter(
        FinancialBalanceLink.id == link_id, FinancialBalanceLink.user_id == current_user.id,
        FinancialSource.provider.notin_(lifecycle.self_managed())).first()
    if link is None:
        fail("Balance link not found.", 404, "NOT_FOUND")
    ensure_plan_active(get_plan_or_404(link.plan_id, current_user.id, db, for_update=True), current_user)
    db.delete(link)
    db.commit()
    return Response(status_code=204)

