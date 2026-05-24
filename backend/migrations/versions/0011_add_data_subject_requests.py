"""add data subject requests

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUEST_TYPE_VALUES = (
    "'access', 'export', 'erase', 'rectify', 'restrict', 'object', 'portability'"
)
_STATUS_VALUES = (
    "'submitted', 'under_review', 'approved', 'rejected', 'fulfilled', 'cancelled'"
)


def upgrade() -> None:
    op.create_table(
        "data_subject_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_type", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'submitted'"),
        ),
        sa.Column("requester_user_id", sa.Uuid(), nullable=True),
        sa.Column("subject_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason_code", sa.String(length=64), nullable=True),
        sa.Column("rejection_reason_code", sa.String(length=64), nullable=True),
        sa.Column("requester_note", sa.Text(), nullable=True),
        sa.Column("internal_note", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extended_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extension_reason_code", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key_hash", sa.String(length=128), nullable=True),
        sa.Column("idempotency_fingerprint", sa.String(length=128), nullable=True),
        sa.Column(
            "idempotency_key_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("export_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("erasure_job_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["requester_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["subject_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            f"request_type IN ({_REQUEST_TYPE_VALUES})",
            name="data_subject_requests_request_type_valid",
        ),
        sa.CheckConstraint(
            f"status IN ({_STATUS_VALUES})",
            name="data_subject_requests_status_valid",
        ),
    )
    op.create_index(
        "ix_data_subject_requests_subject_status_created",
        "data_subject_requests",
        ["subject_user_id", "status", "created_at"],
    )
    op.create_index(
        "ix_data_subject_requests_requester_created",
        "data_subject_requests",
        ["requester_user_id", "created_at"],
    )
    op.create_index(
        "ix_data_subject_requests_status_due",
        "data_subject_requests",
        ["status", "due_at"],
    )
    op.create_index(
        "ix_data_subject_requests_type_status",
        "data_subject_requests",
        ["request_type", "status"],
    )
    op.create_index(
        "ix_data_subject_requests_idempotency_key_hash",
        "data_subject_requests",
        ["idempotency_key_hash"],
    )
    op.create_index(
        "ix_data_subject_requests_idempotency_key_expires_at",
        "data_subject_requests",
        ["idempotency_key_expires_at"],
    )


def downgrade() -> None:
    op.drop_table("data_subject_requests")
