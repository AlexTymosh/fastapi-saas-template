from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.organisations.models.organisation import Organisation
    from app.users.models.user import User


class MembershipRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class Membership(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "organisation_id",
            name="uq_memberships_user_id_organisation_id",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organisation_id: Mapped[UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole, name="membership_role", native_enum=False),
        nullable=False,
        default=MembershipRole.MEMBER,
        server_default=MembershipRole.MEMBER.value,
    )

    user: Mapped[User] = relationship(back_populates="memberships")
    organisation: Mapped[Organisation] = relationship(back_populates="memberships")
