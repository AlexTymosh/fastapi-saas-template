from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.memberships.models.membership import MembershipRole


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    organisation_id: UUID
    role: MembershipRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MembershipCollectionResponse(BaseModel):
    data: list[MembershipResponse]
