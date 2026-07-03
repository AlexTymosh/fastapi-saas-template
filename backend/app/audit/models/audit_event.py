from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.core.db.mixins import UUIDMixin


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
    INVITE_CREATED = "invite_created"
    INVITE_REVOKED = "invite_revoked"
    INVITE_RESENT = "invite_resent"
    USER_SUSPENDED = "user_suspended"
    USER_RESTORED = "user_restored"
    ORGANISATION_SUSPENDED = "organisation_suspended"
    ORGANISATION_RESTORED = "organisation_restored"
    PLATFORM_STAFF_CREATED = "platform_staff_created"
    PLATFORM_STAFF_SUSPENDED = "platform_staff_suspended"
    PLATFORM_STAFF_RESTORED = "platform_staff_restored"
    PLATFORM_STAFF_ROLE_CHANGED = "platform_staff_role_changed"
    CONSENT_GRANTED = "consent_granted"
    CONSENT_WITHDRAWN = "consent_withdrawn"
    PRIVACY_NOTICE_ACCEPTED = "privacy_notice_accepted"
    DATA_SUBJECT_REQUEST_SUBMITTED = "data_subject_request_submitted"
    DATA_SUBJECT_REQUEST_UNDER_REVIEW = "data_subject_request_under_review"
    DATA_SUBJECT_REQUEST_APPROVED = "data_subject_request_approved"
    DATA_SUBJECT_REQUEST_REJECTED = "data_subject_request_rejected"
    DATA_SUBJECT_REQUEST_CANCELLED = "data_subject_request_cancelled"
    DATA_SUBJECT_REQUEST_FULFILLED = "data_subject_request_fulfilled"
    DATA_SUBJECT_REQUEST_ERASURE_EXECUTED = "data_subject_request_erasure_executed"
    DATA_SUBJECT_REQUEST_REPRESENTATIVE_VERIFIED = (
        "data_subject_request_representative_verified"
    )
    DATA_SUBJECT_REQUEST_REPRESENTATIVE_REJECTED = (
        "data_subject_request_representative_rejected"
    )
    EXPORT_ARTIFACT_REQUESTED = "export_artifact_requested"
    EXPORT_ARTIFACT_GENERATED = "export_artifact_generated"
    EXPORT_ARTIFACT_FAILED = "export_artifact_failed"
    EXPORT_ARTIFACT_DOWNLOAD_URL_CREATED = "export_artifact_download_url_created"
    EXPORT_ARTIFACT_DELIVERY_CONFIRMED = "export_artifact_delivery_confirmed"
    EXPORT_ARTIFACT_EXPIRED = "export_artifact_expired"


class AuditTargetType(StrEnum):
    ORGANISATION = "organisation"
    MEMBERSHIP = "membership"
    INVITE = "invite"
    USER = "user"
    PLATFORM_STAFF = "platform_staff"
    PRIVACY_CONSENT = "privacy_consent"
    PRIVACY_NOTICE = "privacy_notice"
    DATA_SUBJECT_REQUEST = "data_subject_request"
    EXPORT_ARTIFACT = "export_artifact"


class AuditEvent(UUIDMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "category IN ('tenant', 'platform', 'security', 'compliance')",
            name="ck_audit_events_category",
        ),
        Index("ix_audit_events_actor_user_id", "actor_user_id"),
        Index("ix_audit_events_category", "category"),
        Index("ix_audit_events_action", "action"),
        Index("ix_audit_events_target", "target_type", "target_id"),
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_legal_hold_until", "legal_hold_until"),
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[UUID | None] = mapped_column(nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    legal_hold_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
