from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDMixin


class DataSubjectRequestType(StrEnum):
    ACCESS = "access"
    EXPORT = "export"
    ERASE = "erase"
    RECTIFY = "rectify"
    RESTRICT = "restrict"
    OBJECT = "object"
    PORTABILITY = "portability"


class DataSubjectRequestStatus(StrEnum):
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


class DataSubjectRequestExecutionStatus(StrEnum):
    NOT_STARTED = "not_started"
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    PARTIALLY_FULFILLED = "partially_fulfilled"
    DELIVERED = "delivered"


class DataSubjectRequestRequesterRole(StrEnum):
    SELF = "self"
    AUTHORISED_REPRESENTATIVE = "authorised_representative"


class DataSubjectRequestRepresentativeStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING_VERIFICATION = "pending_verification"
    VERIFIED = "verified"
    REJECTED = "rejected"


_REQUEST_TYPE_VALUES = ", ".join(repr(item.value) for item in DataSubjectRequestType)
_STATUS_VALUES = ", ".join(repr(item.value) for item in DataSubjectRequestStatus)
_EXECUTION_STATUS_VALUES = ", ".join(
    repr(item.value) for item in DataSubjectRequestExecutionStatus
)
_REQUESTER_ROLE_VALUES = ", ".join(
    repr(item.value) for item in DataSubjectRequestRequesterRole
)
_REPRESENTATIVE_STATUS_VALUES = ", ".join(
    repr(item.value) for item in DataSubjectRequestRepresentativeStatus
)


class DataSubjectRequest(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "data_subject_requests"
    __table_args__ = (
        CheckConstraint(
            f"request_type IN ({_REQUEST_TYPE_VALUES})",
            name="data_subject_requests_request_type_valid",
        ),
        CheckConstraint(
            f"status IN ({_STATUS_VALUES})",
            name="data_subject_requests_status_valid",
        ),
        CheckConstraint(
            f"execution_status IN ({_EXECUTION_STATUS_VALUES})",
            name="data_subject_requests_execution_status_valid",
        ),
        CheckConstraint(
            f"requester_role IN ({_REQUESTER_ROLE_VALUES})",
            name="data_subject_requests_requester_role_valid",
        ),
        CheckConstraint(
            f"representative_status IN ({_REPRESENTATIVE_STATUS_VALUES})",
            name="data_subject_requests_representative_status_valid",
        ),
        Index(
            "ix_data_subject_requests_subject_status_created",
            "subject_user_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_data_subject_requests_requester_created",
            "requester_user_id",
            "created_at",
        ),
        Index("ix_data_subject_requests_status_due", "status", "due_at"),
        Index(
            "ix_data_subject_requests_execution_status_due",
            "execution_status",
            "due_at",
        ),
        Index("ix_data_subject_requests_type_status", "request_type", "status"),
        Index(
            "ix_data_subject_requests_requester_role_status",
            "requester_role",
            "status",
        ),
        Index(
            "ix_data_subject_requests_representative_status",
            "representative_status",
        ),
        Index(
            "ix_data_subject_requests_idempotency_key_hash",
            "idempotency_key_hash",
        ),
        Index(
            "ix_data_subject_requests_idempotency_key_expires_at",
            "idempotency_key_expires_at",
        ),
    )

    request_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DataSubjectRequestStatus.SUBMITTED.value,
        server_default=sa.text("'submitted'"),
    )
    execution_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DataSubjectRequestExecutionStatus.NOT_STARTED.value,
        server_default=sa.text("'not_started'"),
    )

    requester_role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DataSubjectRequestRequesterRole.SELF.value,
        server_default=sa.text("'self'"),
    )
    representative_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DataSubjectRequestRepresentativeStatus.NOT_REQUIRED.value,
        server_default=sa.text("'not_required'"),
    )
    representative_relationship: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    representative_authority_note: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    representative_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    representative_verified_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    representative_rejection_reason_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    requester_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    subject_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewer_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fulfilled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    execution_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_failure_reason_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    execution_failure_detail: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    decision_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejection_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requester_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    extended_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    extension_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    idempotency_key_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_fingerprint: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    idempotency_key_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    export_artifact_id: Mapped[UUID | None] = mapped_column(
        nullable=True,
        info={"privacy_contract": "legacy_export_artifact_pointer"},
    )
    erasure_job_id: Mapped[UUID | None] = mapped_column(nullable=True)
