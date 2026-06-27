from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDMixin


class ExportArtifactStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ExportArtifactFormat(StrEnum):
    JSON_ZIP = "json_zip"


class ExportArtifactStorageBackend(StrEnum):
    LOCAL = "local"
    S3_COMPATIBLE = "s3_compatible"


_STATUS_VALUES = ", ".join(repr(item.value) for item in ExportArtifactStatus)
_FORMAT_VALUES = ", ".join(repr(item.value) for item in ExportArtifactFormat)
_BACKEND_VALUES = ", ".join(repr(item.value) for item in ExportArtifactStorageBackend)


class ExportArtifact(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "export_artifacts"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_STATUS_VALUES})", name="export_artifacts_status_valid"
        ),
        CheckConstraint(
            f"format IN ({_FORMAT_VALUES})", name="export_artifacts_format_valid"
        ),
        CheckConstraint(
            f"storage_backend IN ({_BACKEND_VALUES})",
            name="export_artifacts_storage_backend_valid",
        ),
        Index("ix_export_artifacts_data_subject_request_id", "data_subject_request_id"),
        Index("ix_export_artifacts_subject_user_id", "subject_user_id"),
        Index("ix_export_artifacts_requester_user_id", "requester_user_id"),
        Index("ix_export_artifacts_status_queued_at", "status", "queued_at"),
        Index("ix_export_artifacts_status_expires_at", "status", "expires_at"),
        Index(
            "ix_export_artifacts_status_processing_lease",
            "status",
            "processing_lease_expires_at",
        ),
        Index(
            "ix_export_artifacts_storage_backend_storage_key",
            "storage_backend",
            "storage_key",
        ),
        Index("ix_export_artifacts_created_at", "created_at"),
    )

    data_subject_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("data_subject_requests.id", ondelete="RESTRICT"), nullable=False
    )
    subject_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requester_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    generated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    failure_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processing_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    processing_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    download_url_issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    download_url_issue_count: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default=sa.text("0")
    )
    downloaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    download_count: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default=sa.text("0")
    )
