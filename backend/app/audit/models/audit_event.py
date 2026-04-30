from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from sqlalchemy import JSON, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDMixin


class AuditCategory(StrEnum):
    TENANT = "tenant"
    PLATFORM = "platform"
    SECURITY = "security"
    COMPLIANCE = "compliance"


class AuditAction(StrEnum):
    ORGANISATION_UPDATED = "organisation_updated"
    ORGANISATION_DELETED = "organisation_deleted"
    MEMBERSHIP_ROLE_CHANGED = "membership_role_changed"
    MEMBERSHIP_REMOVED = "membership_removed"
    INVITE_REVOKED = "invite_revoked"
    INVITE_RESENT = "invite_resent"


class AuditEvent(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_target", "target_type", "target_id"),)

    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category: Mapped[AuditCategory] = mapped_column(
        Enum(AuditCategory, name="audit_category", native_enum=False),
        nullable=False,
        index=True,
    )
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name="audit_action", native_enum=False),
        nullable=False,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[UUID | None] = mapped_column(nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
