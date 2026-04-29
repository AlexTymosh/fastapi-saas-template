from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.memberships.models.membership import Membership


class OrganisationStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class Organisation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "organisations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[OrganisationStatus] = mapped_column(
        Enum(OrganisationStatus, native_enum=False),
        nullable=False,
        default=OrganisationStatus.ACTIVE,
        server_default=OrganisationStatus.ACTIVE.value,
    )
    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    suspended_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="organisation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
