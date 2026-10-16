import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.ledger.gating import session_capabilities

if TYPE_CHECKING:
    from app.models.account import CurrentAccount
    from app.models.plan import Plan
    from app.models.progress_point import ProgressPoint
    from app.models.tax_jurisdiction import TaxJurisdiction


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # active_history: change hooks can compare the pre-sign-in value.
    is_anonymous: Mapped[bool] = mapped_column(default=False, server_default="false", active_history=True)
    session_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    # Sign-in provider identities, used by a hosting plug-in's sign-in routes.
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    apple_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    firebase_uid: Mapped[str | None] = mapped_column(String(128), unique=True)
    email_signin_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    # Durable deletion intent/progress; never exposed in ordinary profile responses.
    deletion_state: Mapped[dict | None] = mapped_column(JSONB)
    is_demo: Mapped[bool] = mapped_column(default=False, server_default="false")
    # Private provider credentials are never part of profile/settings responses.
    apple_credential: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        server_default=text("now()"),
    )
    last_login_at: Mapped[datetime | None] = mapped_column()
    settings: Mapped[dict] = mapped_column(
        JSONB,
        server_default=text("'{}'"),
    )

    # Relationships
    plans: Mapped[list["Plan"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    accounts: Mapped[list["CurrentAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    progress_points: Mapped[list["ProgressPoint"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    tax_jurisdictions: Mapped[list["TaxJurisdiction"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def firebase_authenticated(self):
        return self.firebase_uid is not None

    @property
    def deletion_pending(self):
        return self.deletion_state is not None

    @property
    def entitlement(self) -> dict | None:
        """The access policy's account summary for the session response (app.access)."""
        from app.access import policy  # noqa: PLC0415 - app.access imports this module
        return policy().session_entitlement(self)

    @property
    def added_capabilities(self) -> list[str]:
        """Capabilities the access policy and released features add to the session response."""
        from app.access import policy  # noqa: PLC0415 - app.access imports this module
        return policy().session_capabilities(self) + session_capabilities()

    @property
    def auth_providers(self):
        return (["apple"] if self.apple_sub else []) + (["google"] if self.google_sub else []) + (["email"] if self.email_signin_enabled else [])
