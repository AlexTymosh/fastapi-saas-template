from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.organisations.models.organisation import OrganisationStatus
from app.platform.models.platform_staff import PlatformStaffRole, PlatformStaffStatus
from app.users.models.user import UserStatus


class PlatformPaginationQuery(BaseModel):
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class PlatformFullUserListQuery(PlatformPaginationQuery):
    status: UserStatus | None = None
    q: str | None = Field(default=None, min_length=1, max_length=255)


class PlatformLimitedUserListQuery(PlatformPaginationQuery):
    status: UserStatus | None = None
    q: str | None = Field(default=None, min_length=1, max_length=255)
    exact_email: EmailStr | None = None


class PlatformOrganisationListQuery(PlatformPaginationQuery):
    status: OrganisationStatus | None = None
    q: str | None = Field(default=None, min_length=1, max_length=255)


class PlatformLimitedOrganisationListQuery(PlatformPaginationQuery):
    status: OrganisationStatus | None = None
    q: str | None = Field(default=None, min_length=1, max_length=255)


class PlatformStaffListQuery(PlatformPaginationQuery):
    status: PlatformStaffStatus | None = None
    role: PlatformStaffRole | None = None
