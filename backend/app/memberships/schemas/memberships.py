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


class MembershipCollectionMeta(BaseModel):
    total: int


class MembershipCollectionResponse(BaseModel):
    data: list[MembershipResponse]
    meta: MembershipCollectionMeta
    links: dict[str, str]


class UpdateMembershipRoleRequest(BaseModel):
    role: MembershipRole


class DirectoryItemResponse(BaseModel):
    display_name: str
    role_label: str


class DirectoryCollectionMeta(BaseModel):
    total: int


class DirectoryCollectionResponse(BaseModel):
    data: list[DirectoryItemResponse]
    meta: DirectoryCollectionMeta
    links: dict[str, str]
