from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.users.models.user import User


class LawfulBasis(StrEnum):
    CONSENT = "consent"
    CONTRACT = "contract"
    LEGAL_OBLIGATION = "legal_obligation"
    VITAL_INTERESTS = "vital_interests"
    PUBLIC_TASK = "public_task"
    LEGITIMATE_INTERESTS = "legitimate_interests"
    RECOGNISED_LEGITIMATE_INTERESTS = "recognised_legitimate_interests"


class SpecialCategoryCondition(StrEnum):
    EXPLICIT_CONSENT = "explicit_consent"
    EMPLOYMENT_SOCIAL_SECURITY_SOCIAL_PROTECTION = (
        "employment_social_security_social_protection"
    )
    VITAL_INTERESTS = "vital_interests"
    NONPROFIT_BODY = "nonprofit_body"
    MANIFESTLY_PUBLIC = "manifestly_public"
    LEGAL_CLAIMS = "legal_claims"
    SUBSTANTIAL_PUBLIC_INTEREST = "substantial_public_interest"
    REGULATED_SERVICE_PROVISION = "regulated_service_provision"
    PUBLIC_INTEREST_SAFEGUARDING = "public_interest_safeguarding"
    ARCHIVING_RESEARCH_STATISTICS = "archiving_research_statistics"


class ProcessingPurposeFamily(StrEnum):
    ACCOUNT = "account"
    INVITE = "invite"
    AUDIT = "audit"
    MARKETING = "marketing"
    PRODUCT_ANALYTICS = "product_analytics"
    REGULATED_SERVICE_DELIVERY = "regulated_service_delivery"
    LEGAL_COMPLIANCE = "legal_compliance"


_LAWFUL_BASIS_VALUES = ", ".join(repr(item.value) for item in LawfulBasis)
_SPECIAL_CATEGORY_VALUES = ", ".join(
    repr(item.value) for item in SpecialCategoryCondition
)
_PURPOSE_FAMILY_VALUES = ", ".join(repr(item.value) for item in ProcessingPurposeFamily)


class ProcessingPurpose(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "processing_purposes"
    __table_args__ = (
        CheckConstraint(
            f"default_lawful_basis IN ({_LAWFUL_BASIS_VALUES})",
            name="processing_purposes_default_lawful_basis_valid",
        ),
        CheckConstraint(
            f"family IN ({_PURPOSE_FAMILY_VALUES})",
            name="processing_purposes_family_valid",
        ),
        CheckConstraint(
            "default_special_category_condition IS NULL "
            f"OR default_special_category_condition IN ({_SPECIAL_CATEGORY_VALUES})",
            name="processing_purposes_special_category_condition_valid",
        ),
        CheckConstraint(
            "NOT is_special_category OR default_special_category_condition IS NOT NULL",
            name="processing_purposes_special_category_requires_condition",
        ),
        Index("ix_processing_purposes_code", "code", unique=True),
    )

    code: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    family: Mapped[str] = mapped_column(String(64), nullable=False)
    default_lawful_basis: Mapped[str] = mapped_column(String(64), nullable=False)
    is_special_category: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sa.text("false"),
    )
    default_special_category_condition: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    requires_active_consent: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sa.text("false"),
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sa.text("true"),
    )

    authorizations: Mapped[list[DataProcessingAuthorization]] = relationship(
        back_populates="purpose",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    consent_records: Mapped[list[ConsentRecord]] = relationship(
        back_populates="purpose",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DataProcessingAuthorization(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "data_processing_authorizations"
    __table_args__ = (
        CheckConstraint(
            f"lawful_basis IN ({_LAWFUL_BASIS_VALUES})",
            name="data_processing_authorizations_lawful_basis_valid",
        ),
        CheckConstraint(
            "special_category_condition IS NULL "
            f"OR special_category_condition IN ({_SPECIAL_CATEGORY_VALUES})",
            name="data_processing_authorizations_special_condition_valid",
        ),
        Index(
            "ix_data_processing_authorizations_subject_purpose_active",
            "subject_user_id",
            "purpose_id",
            "active",
        ),
        Index("ix_data_processing_authorizations_valid_until", "valid_until"),
    )

    subject_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    purpose_id: Mapped[UUID] = mapped_column(
        ForeignKey("processing_purposes.id", ondelete="CASCADE"),
        nullable=False,
    )
    lawful_basis: Mapped[str] = mapped_column(String(64), nullable=False)
    special_category_condition: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sa.text("true"),
    )
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)

    subject_user: Mapped[User] = relationship()
    purpose: Mapped[ProcessingPurpose] = relationship(back_populates="authorizations")


class ConsentRecord(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "consent_records"
    __table_args__ = (
        Index(
            "ix_consent_records_subject_purpose_withdrawn",
            "subject_user_id",
            "purpose_id",
            "withdrawn_at",
        ),
        Index("ix_consent_records_authorization_id", "authorization_id"),
    )

    subject_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    purpose_id: Mapped[UUID] = mapped_column(
        ForeignKey("processing_purposes.id", ondelete="CASCADE"),
        nullable=False,
    )
    authorization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("data_processing_authorizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    privacy_notice_version: Mapped[str] = mapped_column(String(64), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    withdrawal_reason_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    subject_user: Mapped[User] = relationship()
    purpose: Mapped[ProcessingPurpose] = relationship(back_populates="consent_records")
    authorization: Mapped[DataProcessingAuthorization | None] = relationship()


class PrivacyNoticeAcceptance(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "privacy_notice_acceptances"
    __table_args__ = (
        Index(
            "uq_privacy_notice_acceptances_subject_version",
            "subject_user_id",
            "notice_version",
            unique=True,
        ),
        Index("ix_privacy_notice_acceptances_accepted_at", "accepted_at"),
    )

    subject_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    notice_version: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)

    subject_user: Mapped[User] = relationship()
