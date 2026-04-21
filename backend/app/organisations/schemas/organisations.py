from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")


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
        slug = value.strip().lower()
        if not slug:
            msg = "Organisation slug cannot be blank"
            raise ValueError(msg)
        if not _SLUG_PATTERN.fullmatch(slug):
            msg = "Slug must contain only lowercase letters, digits, and hyphens"
            raise ValueError(msg)
        return slug


class UpdateOrganisationSlugRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=255)


class OrganisationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime
