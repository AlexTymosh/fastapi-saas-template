from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.audit.reasons import OperationalReasonCode, normalise_legacy_reason
from app.users.models.user import UserStatus


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: OperationalReasonCode | None = None
    legacy_reason: str | None = Field(
        default=None,
        validation_alias="reason",
        exclude=True,
        max_length=500,
    )

    @model_validator(mode="after")
    def require_reason_code(self):
        if self.reason_code is None:
            reason_code = normalise_legacy_reason(
                self.legacy_reason,
                required=True,
            )
            object.__setattr__(self, "reason_code", reason_code)
        return self

    @property
    def reason(self) -> str:
        assert self.reason_code is not None
        return self.reason_code.value


class PlatformUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: EmailStr | None
    email_verified: bool
    first_name: str | None
    last_name: str | None
    status: UserStatus
    suspended_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PlatformLimitedUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    first_name: str | None
    last_name: str | None
    status: UserStatus
    created_at: datetime


class PlatformUsersMeta(BaseModel):
    total: int
    limit: int
    offset: int


class PlatformUsersCollectionResponse(BaseModel):
    data: list[PlatformUserResponse]
    meta: PlatformUsersMeta
    links: dict[str, str]


class PlatformLimitedUsersCollectionResponse(BaseModel):
    data: list[PlatformLimitedUserResponse]
    meta: PlatformUsersMeta
    links: dict[str, str]
