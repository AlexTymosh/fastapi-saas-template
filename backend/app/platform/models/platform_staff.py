from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDMixin


class PlatformStaff(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "platform_staff"
    __table_args__ = (
        CheckConstraint(
            "role IN ('platform_admin', 'support_agent', 'compliance_officer')",
            name="ck_platform_staff_role",
        ),
        CheckConstraint(
            "status IN ('active', 'suspended')",
            name="ck_platform_staff_status",
        ),
        Index("ix_platform_staff_role", "role"),
        Index("ix_platform_staff_status", "status"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
