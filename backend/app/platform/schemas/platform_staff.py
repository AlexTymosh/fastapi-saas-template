from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.platform.models.platform_staff import PlatformStaffRole, PlatformStaffStatus


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Reason cannot be blank")
        return trimmed


class CreatePlatformStaffRequest(ReasonRequest):
    user_id: UUID
    role: PlatformStaffRole


class UpdatePlatformStaffRoleRequest(ReasonRequest):
    role: PlatformStaffRole


class PlatformStaffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    role: PlatformStaffRole
    status: PlatformStaffStatus
    created_by_user_id: UUID | None
    suspended_at: datetime | None
    suspended_reason: str | None
    created_at: datetime
    updated_at: datetime


class PlatformStaffMeta(BaseModel):
    total: int
    limit: int
    offset: int


class PlatformStaffCollectionResponse(BaseModel):
    data: list[PlatformStaffResponse]
    meta: PlatformStaffMeta
    links: dict[str, str]
