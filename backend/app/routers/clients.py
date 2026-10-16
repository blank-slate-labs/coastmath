import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error
from app.models.plan import Plan
from app.models.planning_client import PlanningClient
from app.models.user import User
from app.schemas.planning_client import ClientRead, ClientUpdate

router = APIRouter(prefix="/clients", tags=["clients"])


def get_client_or_404(client_id: uuid.UUID, user_id: uuid.UUID, db: Session) -> PlanningClient:
    client = db.query(PlanningClient).filter_by(id=client_id, user_id=user_id).first()
    if client is None:
        raise api_error(404, "NOT_FOUND", "Client not found")
    return client


@router.get("", response_model=list[ClientRead])
def list_clients(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(PlanningClient).filter_by(user_id=current_user.id).order_by(PlanningClient.name, PlanningClient.id).all()


def personal_client(current_user: User, db: Session) -> PlanningClient:
    """Resolve the user's private plan container without a client-setup step.

    The existing ownership model stays intact. Lock the identity row before
    reading its pointer so concurrent devices cannot create extra containers.
    Existing client records and their plans are never renamed or reparented.
    """
    user = db.query(User).filter_by(id=current_user.id).populate_existing().with_for_update().one()
    settings = dict(user.settings or {})
    try:
        client_id = uuid.UUID(settings.get("personal_workspace_client_id", ""))
    except (ValueError, TypeError, AttributeError):
        client_id = None
    client = db.query(PlanningClient).filter_by(id=client_id, user_id=user.id).first() if client_id else None
    if client is None:
        client = PlanningClient(user_id=user.id, name="My plans")
        db.add(client)
        db.flush()
        settings["personal_workspace_client_id"] = str(client.id)
        user.settings = settings
    return client


@router.post("/personal", response_model=ClientRead)
def ensure_personal_client(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    client = personal_client(current_user, db)
    db.commit()
    db.refresh(client)
    return client


@router.put("/{client_id}", response_model=ClientRead)
def update_client(client_id: uuid.UUID, body: ClientUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    client = get_client_or_404(client_id, current_user.id, db)
    for key, value in body.model_dump().items():
        setattr(client, key, value)
    db.commit()
    db.refresh(client)
    return client


@router.delete("/{client_id}", status_code=204)
def delete_client(client_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    client = get_client_or_404(client_id, current_user.id, db)
    if db.query(Plan.id).filter_by(client_id=client_id).first():
        raise api_error(409, "CONFLICT", "This client still has plans. Archive the client or delete their plans first.")
    db.delete(client)
    db.commit()
    return Response(status_code=204)
