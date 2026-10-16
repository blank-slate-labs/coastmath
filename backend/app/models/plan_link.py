"""Identity links between a scenario plan's rows and its Main plan's rows.

A scenario is a complete, ordinary plan (app.scenarios). Each link pairs one
Main row (or the Main plan itself, or one of Main's whole lists) with the
scenario's copy and keeps ``base``: Main's values at the last sync, already
translated into the scenario's IDs and canonically encoded
(app.scenarios.values). A scenario value that differs from ``base`` is an
override the scenario keeps when Main changes.
"""
import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PlanLink(Base):
    __tablename__ = "plan_links"
    # The unique index leads with scenario_plan_id, so it also serves lookups
    # and cascading deletes by scenario plan.
    __table_args__ = (
        UniqueConstraint("scenario_plan_id", "kind", "main_row_id", name="uq_plan_links_scenario_kind_main"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    scenario_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    # A registry kind (app.scenarios.registry): "plan", a row kind or a
    # whole-list kind.
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # Main's row ID; for "plan" and whole-list kinds, Main's plan ID.
    main_row_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # The scenario's copy; NULL when the scenario removed it.
    scenario_row_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    base: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
