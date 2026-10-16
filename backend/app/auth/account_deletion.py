"""Delete the signed-in account and all owned data through database cascades."""
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.router import _is_secure
from app.db import get_db
from app.ledger import connections as ledger_connections
from app.ledger.balances import fail, lock_user
from app.ledger.providers.errors import ProviderError
from app.models.user import User
from app.rate_limit import limiter

# A plug-in may serve this route instead (app.plugins).
router = APIRouter(prefix="/auth", tags=["auth"])


class DeleteAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal["DELETE"]


@router.delete("/me", status_code=204)
@limiter.limit("5/minute")
def delete_account(request: Request, body: DeleteAccountRequest,
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    user_id = current_user.id
    lock_user(db, user_id)
    get_current_user(request, db)  # Recheck revocation after acquiring the lock.
    disconnect_ledger_providers(db, user_id)
    # All ownership FKs cascade, including plans and provider receipts.
    db.execute(delete(User).where(User.id == user_id))
    db.commit()
    return deleted_response()


def disconnect_ledger_providers(db, user_id):
    """Drop every transaction provider's credential before deletion.

    Each provider's adapter revokes remote access first (SimpleFIN needs no
    remote call; Plaid removes its item). A failed revocation keeps the account
    for retry.
    """
    try:
        ledger_connections.disconnect_all(db, user_id)
    except ProviderError:
        db.commit()
        fail("An institution could not be disconnected. Your account has not been deleted. Please retry; already disconnected institutions remain disconnected.", 503, "DELETION_CONNECTION_PENDING")


def deleted_response():
    response = Response(status_code=204)
    response.delete_cookie("session", httponly=True, secure=_is_secure(), samesite="lax")
    return response
