from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.invites.models.invite import InviteStatus
from app.memberships.models.membership import MembershipRole


class CreateInviteRequest(BaseModel):
    email: EmailStr
    role: MembershipRole = MembershipRole.MEMBER


class InviteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    organisation_id: UUID
    role: MembershipRole
    status: InviteStatus
    created_at: datetime
    updated_at: datetime


class InviteCreateResponse(BaseModel):
    invite: InviteResponse
    token: str


class AcceptInviteResponse(BaseModel):
    membership_id: UUID
    organisation_id: UUID
    role: MembershipRole
