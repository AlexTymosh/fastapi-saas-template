from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.audit.reasons import OperationalReasonCode, normalise_legacy_reason
from app.invites.models.invite import InviteStatus
from app.memberships.models.membership import MembershipRole


class CreateInviteRequest(BaseModel):
    email: EmailStr
    role: MembershipRole = MembershipRole.MEMBER

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: MembershipRole) -> MembershipRole:
        if value == MembershipRole.OWNER:
            msg = "Owner role cannot be assigned via invite"
            raise ValueError(msg)
        return value


class InviteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    organisation_id: UUID
    role: MembershipRole
    status: InviteStatus
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AcceptInviteRequest(BaseModel):
    token: str = Field(max_length=4096)

    @field_validator("token")
    @classmethod
    def validate_token(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "Token must not be empty"
            raise ValueError(msg)
        return normalized


class AcceptInviteResponse(BaseModel):
    membership_id: UUID
    organisation_id: UUID
    role: MembershipRole


class RevokeInviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: OperationalReasonCode | None = None
    legacy_reason: str | None = Field(
        default=None,
        validation_alias="reason",
        exclude=True,
        max_length=500,
    )

    @model_validator(mode="after")
    def normalise_reason(self):
        if self.reason_code is None:
            reason_code = normalise_legacy_reason(
                self.legacy_reason,
                required=False,
            )
            object.__setattr__(self, "reason_code", reason_code)
        return self

    @property
    def reason(self) -> str | None:
        if self.reason_code is None:
            return None
        return self.reason_code.value
