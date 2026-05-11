from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.users.models.user import User, UserStatus


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Reason cannot be blank")
        return trimmed


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
    id: UUID
    masked_email: str | None
    first_name: str | None
    last_name: str | None
    status: UserStatus
    created_at: datetime

    @staticmethod
    def mask_email(email: str | None) -> str | None:
        if email is None:
            return None
        local_part, separator, domain = email.partition("@")
        if not separator:
            return None
        if len(local_part) <= 1:
            masked_local = "*"
        elif len(local_part) == 2:
            masked_local = f"{local_part[0]}*"
        else:
            masked_local = (
                f"{local_part[0]}{'*' * (len(local_part) - 2)}{local_part[-1]}"
            )
        return f"{masked_local}@{domain}"

    @classmethod
    def from_user(cls, user: User) -> "PlatformLimitedUserResponse":
        return cls(
            id=user.id,
            masked_email=cls.mask_email(user.email),
            first_name=user.first_name,
            last_name=user.last_name,
            status=user.status,
            created_at=user.created_at,
        )


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
