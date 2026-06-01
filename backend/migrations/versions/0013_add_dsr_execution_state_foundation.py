"""add DSR execution state foundation

Revision ID: 0013_dsr_exec_state
Revises: 0012_add_export_artifacts
Create Date: 2026-06-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_dsr_exec_state"
down_revision: str | None = "0012_add_export_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXECUTION_STATUS_VALUES = (
    "'not_started', 'queued', 'processing', 'ready', 'failed', "
    "'partially_fulfilled', 'delivered'"
)


def upgrade() -> None:
    with op.batch_alter_table("data_subject_requests") as batch_op:
        batch_op.add_column(
            sa.Column(
                "execution_status",
                sa.String(length=32),
                server_default=sa.text("'not_started'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("execution_started_at", sa.DateTime(timezone=True))
        )
        batch_op.add_column(
            sa.Column("execution_completed_at", sa.DateTime(timezone=True))
        )
        batch_op.add_column(
            sa.Column("execution_failed_at", sa.DateTime(timezone=True))
        )
        batch_op.add_column(
            sa.Column("execution_failure_reason_code", sa.String(length=64))
        )
        batch_op.add_column(
            sa.Column("execution_failure_detail", sa.String(length=255))
        )
        batch_op.create_check_constraint(
            "data_subject_requests_execution_status_valid",
            f"execution_status IN ({_EXECUTION_STATUS_VALUES})",
        )

    op.create_index(
        "ix_data_subject_requests_execution_status_due",
        "data_subject_requests",
        ["execution_status", "due_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_data_subject_requests_execution_status_due",
        table_name="data_subject_requests",
    )

    with op.batch_alter_table("data_subject_requests") as batch_op:
        batch_op.drop_constraint(
            "data_subject_requests_execution_status_valid",
            type_="check",
        )
        batch_op.drop_column("execution_failure_detail")
        batch_op.drop_column("execution_failure_reason_code")
        batch_op.drop_column("execution_failed_at")
        batch_op.drop_column("execution_completed_at")
