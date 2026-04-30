from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.core.db.mixins import UUIDMixin, utcnow


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


class AuditTargetType(StrEnum):
    ORGANISATION = "organisation"
    MEMBERSHIP = "membership"
    INVITE = "invite"
    USER = "user"


class AuditEvent(UUIDMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "category IN ('tenant', 'platform', 'security', 'compliance')",
            name="ck_audit_events_category_valid",
        ),
        Index("ix_audit_events_actor_user_id", "actor_user_id"),
        Index("ix_audit_events_category", "category"),
        Index("ix_audit_events_action", "action"),
        Index("ix_audit_events_target", "target_type", "target_id"),
        Index("ix_audit_events_created_at", "created_at"),
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[AuditCategory] = mapped_column(String(32), nullable=False)
    action: Mapped[AuditAction] = mapped_column(String(100), nullable=False)
    target_type: Mapped[AuditTargetType] = mapped_column(String(64), nullable=False)
    target_id: Mapped[UUID | None] = mapped_column(nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
