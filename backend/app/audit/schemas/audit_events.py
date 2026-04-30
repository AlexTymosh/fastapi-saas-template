from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.audit.models.audit_event import AuditAction, AuditCategory


class AuditEventResponse(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    category: AuditCategory
    action: AuditAction
    target_type: str
    target_id: UUID | None
    reason: str | None
    metadata_json: dict[str, object] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
