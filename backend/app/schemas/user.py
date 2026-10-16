import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SessionCreate(BaseModel):
    # Sessions no longer seed sample data. Shipped clients still send
    # seed_demo and client_workspace, so both stay accepted and are ignored.
    seed_demo: bool = True
    client_workspace: bool = False
    read_only_demo: bool = False


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    is_anonymous: bool
    is_demo: bool = False
    firebase_authenticated: bool = False
    deletion_pending: bool = False
    auth_providers: list[str] = []
    capabilities: list[str] = ["personal_onboarding", "profile_edit", "client_workspaces", "personal_plans"]
    # Additive: the access policy's summary of this account at response time
    # (app.access); null without one.
    entitlement: dict[str, Any] | None = None
    # Read from the account and merged into ``capabilities``; never serialized.
    added_capabilities: list[str] = Field(default_factory=list, exclude=True)

    @model_validator(mode="after")
    def _added_capabilities(self) -> "SessionRead":
        # Additive: older clients ignore unknown capabilities. Presentation only;
        # routes enforce access themselves.
        for capability in self.added_capabilities:
            if capability not in self.capabilities:
                self.capabilities = [*self.capabilities, capability]
        return self


class UserProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=255)

    @field_validator("display_name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter a name")
        return value


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None = None
    avatar_url: str | None = None
    created_at: datetime
