from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.memberships.models.membership import Membership


class Organisation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "organisations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="organisation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
