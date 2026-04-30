from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PlatformOrganisationResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    status: str
    suspended_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrganisationCorrectionRequest(BaseModel):
    name: str | None = None
    slug: str | None = None
    reason: str = Field(min_length=1, max_length=500)
