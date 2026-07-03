"""add DSR representative intake metadata

Revision ID: 0016_dsr_representative_intake
Revises: 0015_export_delivery_evidence
Create Date: 2026-07-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_dsr_representative_intake"
down_revision: str | None = "0015_export_delivery_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_REQUESTER_ROLE_CHECK = "requester_role IN ('self','authorised_representative')"
_REPRESENTATIVE_STATUS_CHECK = (
    "representative_status IN "
    "('not_required','pending_verification','verified','rejected')"
)


def upgrade() -> None:
    with op.batch_alter_table("data_subject_requests") as batch_op:
        batch_op.add_column(
            sa.Column(
                "requester_role",
                sa.String(length=32),
                server_default=sa.text("'self'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "representative_status",
                sa.String(length=32),
                server_default=sa.text("'not_required'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("representative_relationship", sa.String(length=64))
        )
        batch_op.add_column(sa.Column("representative_authority_note", sa.Text()))
        batch_op.add_column(
            sa.Column("representative_verified_at", sa.DateTime(timezone=True))
        )
        batch_op.add_column(sa.Column("representative_verified_by_user_id", sa.Uuid()))
        batch_op.add_column(
            sa.Column("representative_rejection_reason_code", sa.String(length=64))
        )
        batch_op.create_foreign_key(
            "fk_dsr_rep_verified_by_user_id",
            "users",
            ["representative_verified_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "data_subject_requests_requester_role_valid",
            _REQUESTER_ROLE_CHECK,
        )
        batch_op.create_check_constraint(
            "data_subject_requests_representative_status_valid",
            _REPRESENTATIVE_STATUS_CHECK,
        )
        batch_op.create_index(
            "ix_data_subject_requests_requester_role_status",
            ["requester_role", "status"],
        )
        batch_op.create_index(
            "ix_data_subject_requests_representative_status",
            ["representative_status"],
        )


def downgrade() -> None:
    with op.batch_alter_table("data_subject_requests") as batch_op:
        batch_op.drop_index("ix_data_subject_requests_representative_status")
        batch_op.drop_index("ix_data_subject_requests_requester_role_status")
        batch_op.drop_constraint(
            "data_subject_requests_representative_status_valid",
            type_="check",
        )
        batch_op.drop_constraint(
            "data_subject_requests_requester_role_valid",
            type_="check",
        )
        batch_op.drop_constraint(
            "fk_dsr_rep_verified_by_user_id",
            type_="foreignkey",
        )
        batch_op.drop_column("representative_rejection_reason_code")
        batch_op.drop_column("representative_verified_by_user_id")
        batch_op.drop_column("representative_verified_at")
        batch_op.drop_column("representative_authority_note")
        batch_op.drop_column("representative_relationship")
        batch_op.drop_column("representative_status")
        batch_op.drop_column("requester_role")
