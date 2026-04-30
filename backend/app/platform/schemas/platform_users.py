from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class PlatformUserResponse(BaseModel):
    id: UUID
    email: str | None
    email_verified: bool
    first_name: str | None
    last_name: str | None
    status: str
    suspended_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
