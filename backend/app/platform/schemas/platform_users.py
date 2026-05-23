from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.audit.reasons import OperationalReasonCode, normalise_legacy_reason_payload
from app.users.models.user import UserStatus


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: OperationalReasonCode = Field(
        description=(
            "Structured operational reason code. The legacy 'reason' input "
            "field is accepted for backward compatibility only when its value "
            "is an existing structured reason code. Free-text legacy reasons "
            "are rejected before validation to avoid persisting operational "
            "details."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def normalise_legacy_reason_alias(cls, data: object) -> object:
        return normalise_legacy_reason_payload(data, required=True)

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
