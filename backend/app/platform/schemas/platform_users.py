from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.users.models.user import UserStatus


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


class PlatformUsersMeta(BaseModel):
    total: int
    limit: int
    offset: int


class PlatformUsersCollectionResponse(BaseModel):
    data: list[PlatformUserResponse]
    meta: PlatformUsersMeta
    links: dict[str, str]
