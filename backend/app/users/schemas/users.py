from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.memberships.models.membership import MembershipRole
from app.users.models.user import UserStatus


class MembershipSummary(BaseModel):
    organisation_id: UUID
    role: MembershipRole


class UserMeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_auth_id: str
    email: EmailStr | None
    email_verified: bool
    first_name: str | None
    last_name: str | None
    onboarding_completed: bool
    status: UserStatus
    membership: MembershipSummary | None
    created_at: datetime
    updated_at: datetime
