from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.memberships.models.membership import Membership


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    keycloak_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
    )
    email: Mapped[str | None] = mapped_column(
        String(320),
        nullable=True,
        unique=True,
    )

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
