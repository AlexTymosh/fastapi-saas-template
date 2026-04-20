from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_auth_id: str
    email: str | None
    email_verified: bool
    first_name: str | None
    last_name: str | None
    onboarding_completed: bool
    has_any_organisation: bool
