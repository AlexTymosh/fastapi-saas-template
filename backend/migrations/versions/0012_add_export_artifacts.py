"""add export artifacts

Revision ID: 0012_add_export_artifacts
Revises: 0011
Create Date: 2026-05-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_add_export_artifacts"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "export_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("data_subject_request_id", sa.Uuid(), nullable=False),
        sa.Column("subject_user_id", sa.Uuid(), nullable=True),
        sa.Column("requester_user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("storage_backend", sa.String(length=32), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("generated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("failure_reason_code", sa.String(length=64), nullable=True),
        sa.Column("failure_detail", sa.String(length=255), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_token", sa.String(length=36), nullable=True),
        sa.Column(
            "processing_lease_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("download_count", sa.Integer(), server_default="0", nullable=False),
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
        sa.CheckConstraint(
            "status IN ('queued','processing','ready','failed','expired','cancelled')",
            name="export_artifacts_status_valid",
        ),
        sa.CheckConstraint(
            "format IN ('json_zip')", name="export_artifacts_format_valid"
        ),
        sa.CheckConstraint(
            "storage_backend IN ('local','s3_compatible')",
            name="export_artifacts_storage_backend_valid",
        ),
        sa.ForeignKeyConstraint(
            ["data_subject_request_id"],
            ["data_subject_requests.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["subject_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["requester_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["generated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_export_artifacts_data_subject_request_id",
        "export_artifacts",
        ["data_subject_request_id"],
    )
    op.create_index(
        "ix_export_artifacts_subject_user_id", "export_artifacts", ["subject_user_id"]
    )
    op.create_index(
        "ix_export_artifacts_requester_user_id",
        "export_artifacts",
        ["requester_user_id"],
    )
    op.create_index(
        "ix_export_artifacts_status_queued_at",
        "export_artifacts",
        ["status", "queued_at"],
    )
    op.create_index(
        "ix_export_artifacts_status_expires_at",
        "export_artifacts",
        ["status", "expires_at"],
    )
    op.create_index(
        "ix_export_artifacts_status_processing_lease",
        "export_artifacts",
        ["status", "processing_lease_expires_at"],
    )
    op.create_index(
        "ix_export_artifacts_storage_backend_storage_key",
        "export_artifacts",
        ["storage_backend", "storage_key"],
    )
    op.create_index(
        "ix_export_artifacts_created_at", "export_artifacts", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_export_artifacts_created_at", table_name="export_artifacts")
    op.drop_index(
        "ix_export_artifacts_storage_backend_storage_key", table_name="export_artifacts"
    )
    op.drop_index(
        "ix_export_artifacts_status_processing_lease", table_name="export_artifacts"
    )
    op.drop_index(
        "ix_export_artifacts_status_expires_at", table_name="export_artifacts"
    )
    op.drop_index("ix_export_artifacts_status_queued_at", table_name="export_artifacts")
    op.drop_index(
        "ix_export_artifacts_requester_user_id", table_name="export_artifacts"
    )
    op.drop_index("ix_export_artifacts_subject_user_id", table_name="export_artifacts")
    op.drop_index(
        "ix_export_artifacts_data_subject_request_id", table_name="export_artifacts"
    )
    op.drop_table("export_artifacts")
