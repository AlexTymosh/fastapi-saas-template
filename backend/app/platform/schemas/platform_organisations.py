from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.audit.reasons import OperationalReasonCode, normalise_legacy_reason_payload
from app.organisations.models.organisation import OrganisationStatus
from app.organisations.schemas.organisations import normalize_and_validate_slug


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


class PlatformLimitedOrganisationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str
    status: OrganisationStatus
    created_at: datetime


class PlatformOrganisationPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    reason_code: OperationalReasonCode = Field(
        description=(
            "Structured operational reason code. The legacy 'reason' input "
            "field is accepted for backward compatibility only when it does "
            "not contain obvious secrets, contact details, special-category "
            "personal data, or sensitive operational details; arbitrary legacy "
            "free text is persisted as 'other'."
        ),
    )

    @property
    def reason(self) -> str:
        return self.reason_code.value

    @model_validator(mode="before")
    @classmethod
    def normalise_legacy_reason_alias(cls, data: object) -> object:
        return normalise_legacy_reason_payload(data, required=True)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Organisation name cannot be blank")
        return normalized

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_and_validate_slug(value)

    @model_validator(mode="after")
    def check_any_profile_field(self):
        if self.name is None and self.slug is None:
            raise ValueError("At least one of 'name' or 'slug' must be provided")
        return self


class PlatformOrganisationsMeta(BaseModel):
    total: int
    limit: int
    offset: int


class PlatformOrganisationsCollectionResponse(BaseModel):
    data: list[PlatformOrganisationResponse]
    meta: PlatformOrganisationsMeta
    links: dict[str, str]


class PlatformLimitedOrganisationsCollectionResponse(BaseModel):
    data: list[PlatformLimitedOrganisationResponse]
    meta: PlatformOrganisationsMeta
    links: dict[str, str]
