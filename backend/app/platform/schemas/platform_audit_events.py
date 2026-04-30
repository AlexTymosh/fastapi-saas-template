from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    category: str
    action: str
    target_type: str
    target_id: UUID | None
    reason: str | None
    metadata_json: dict[str, object] | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
