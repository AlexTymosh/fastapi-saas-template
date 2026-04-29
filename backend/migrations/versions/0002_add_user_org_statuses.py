"""add user and organisation statuses

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="active",
            )
        )
        batch_op.add_column(
            sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("suspended_reason", sa.String(length=500), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_users_status_valid",
            "status IN ('active', 'suspended')",
        )

    with op.batch_alter_table("organisations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="active",
            )
        )
        batch_op.add_column(
            sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("suspended_reason", sa.String(length=500), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_organisations_status_valid",
            "status IN ('active', 'suspended')",
        )


def downgrade() -> None:
    with op.batch_alter_table("organisations") as batch_op:
        batch_op.drop_constraint("ck_organisations_status_valid", type_="check")
        batch_op.drop_column("suspended_reason")
        batch_op.drop_column("suspended_at")
        batch_op.drop_column("status")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_status_valid", type_="check")
        batch_op.drop_column("suspended_reason")
        batch_op.drop_column("suspended_at")
        batch_op.drop_column("status")
