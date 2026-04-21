from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDMixin
from app.memberships.models.membership import MembershipRole

if TYPE_CHECKING:
    from app.organisations.models.organisation import Organisation


class InviteStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"


class Invite(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "invites"
    __table_args__ = (UniqueConstraint("token", name="uq_invites_token"),)

    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    organisation_id: Mapped[UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole, name="invite_role", native_enum=False),
        nullable=False,
    )
    status: Mapped[InviteStatus] = mapped_column(
        Enum(InviteStatus, name="invite_status", native_enum=False),
        nullable=False,
        default=InviteStatus.PENDING,
        server_default=InviteStatus.PENDING.value,
    )
    token: Mapped[str] = mapped_column(String(255), nullable=False)

    organisation: Mapped[Organisation] = relationship()
