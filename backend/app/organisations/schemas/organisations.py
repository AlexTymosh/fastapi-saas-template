from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.organisations.models.organisation import OrganisationStatus

_SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")


def normalize_and_validate_slug(value: str) -> str:
    slug = value.strip().lower()
    if not slug:
        msg = "Organisation slug cannot be blank"
        raise ValueError(msg)
    if not _SLUG_PATTERN.fullmatch(slug):
        msg = "Slug must contain only lowercase letters, digits, and hyphens"
        raise ValueError(msg)
    return slug


class CreateOrganisationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            msg = "Organisation name cannot be blank"
            raise ValueError(msg)
        return name

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return normalize_and_validate_slug(value)


class UpdateOrganisationRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip()
        if not name:
            msg = "Organisation name cannot be blank"
            raise ValueError(msg)
        return name

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_and_validate_slug(value)

    @model_validator(mode="after")
    def validate_patch_payload(self) -> UpdateOrganisationRequest:
        if self.name is None and self.slug is None:
            msg = "At least one of 'name' or 'slug' must be provided"
            raise ValueError(msg)
        return self


class OrganisationDirectoryItemResponse(BaseModel):
    display_name: str
    role_label: str


class OrganisationDirectoryMeta(BaseModel):
    total: int


class OrganisationDirectoryResponse(BaseModel):
    data: list[OrganisationDirectoryItemResponse]
    meta: OrganisationDirectoryMeta
    links: dict[str, str]


class UpdateOrganisationSlugRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=255)

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return normalize_and_validate_slug(value)


class OrganisationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    status: OrganisationStatus
    created_at: datetime
    updated_at: datetime
