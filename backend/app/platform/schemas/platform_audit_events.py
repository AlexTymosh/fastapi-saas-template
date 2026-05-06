from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.audit.models.audit_event import AuditEvent


class PlatformAuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
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


class PlatformLimitedAuditEventResponse(BaseModel):
    id: UUID
    category: str
    action: str
    target_type: str
    target_id: UUID | None
    has_actor: bool
    has_metadata: bool
    has_reason: bool
    created_at: datetime

    @classmethod
    def from_audit_event(
        cls, audit_event: AuditEvent
    ) -> "PlatformLimitedAuditEventResponse":
        return cls(
            id=audit_event.id,
            category=audit_event.category,
            action=audit_event.action,
            target_type=audit_event.target_type,
            target_id=audit_event.target_id,
            has_actor=audit_event.actor_user_id is not None,
            has_metadata=audit_event.metadata_json is not None,
            has_reason=audit_event.reason is not None,
            created_at=audit_event.created_at,
        )


class PlatformAuditEventsMeta(BaseModel):
    total: int
    limit: int
    offset: int


class PlatformAuditEventsCollectionResponse(BaseModel):
    data: list[PlatformAuditEventResponse]
    meta: PlatformAuditEventsMeta
    links: dict[str, str]


class PlatformLimitedAuditEventsCollectionResponse(BaseModel):
    data: list[PlatformLimitedAuditEventResponse]
    meta: PlatformAuditEventsMeta
    links: dict[str, str]
