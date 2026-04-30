from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class UpdateMembershipRoleRequest(BaseModel):
    role: MembershipRole


class MembershipCollectionMeta(BaseModel):
    total: int


class MembershipCollectionResponse(BaseModel):
    data: list[MembershipResponse]
    meta: MembershipCollectionMeta
    links: dict[str, str]


class RemoveMembershipRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
