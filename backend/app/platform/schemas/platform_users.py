from datetime import datetime
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)

from app.audit.reasons import OperationalReasonCode, normalise_legacy_reason
from app.users.models.user import UserStatus


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: OperationalReasonCode = Field(
        validation_alias=AliasChoices("reason_code", "reason"),
        description=(
            "Structured operational reason code. The legacy 'reason' input "
            "field is accepted for backward compatibility and arbitrary legacy "
            "free text is persisted as 'other'."
        ),
    )

    @field_validator("reason_code", mode="before")
    @classmethod
    def normalise_reason_code(cls, value: object) -> OperationalReasonCode:
        reason_code = normalise_legacy_reason(value, required=True)
        assert reason_code is not None
        return reason_code

    @property
    def reason(self) -> str:
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
