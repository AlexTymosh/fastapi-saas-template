from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.organisations.models.organisation import OrganisationStatus


class PlatformOrganisationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str
    status: OrganisationStatus
    suspended_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PlatformOrganisationsMeta(BaseModel):
    total: int
    limit: int
    offset: int


class PlatformOrganisationsCollectionResponse(BaseModel):
    data: list[PlatformOrganisationResponse]
    meta: PlatformOrganisationsMeta
    links: dict[str, str]


class PlatformOrganisationPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("name", "slug", "reason")
    @classmethod
    def trim_text(cls, value: str | None):
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Field cannot be blank")
        return trimmed

    @model_validator(mode="after")
    def ensure_any_change_field(self):
        if self.name is None and self.slug is None:
            raise ValueError("At least one of name or slug must be provided")
        return self
