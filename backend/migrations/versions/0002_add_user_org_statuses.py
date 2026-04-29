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

user_status = sa.Enum("active", "suspended", name="user_status", native_enum=False)
organisation_status = sa.Enum(
    "active",
    "suspended",
    name="organisation_status",
    native_enum=False,
)


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("status", user_status, nullable=False, server_default="active"),
    )
    op.add_column(
        "users", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("suspended_reason", sa.String(length=500), nullable=True)
    )

    op.add_column(
        "organisations",
        sa.Column(
            "status",
            organisation_status,
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "organisations",
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organisations",
        sa.Column("suspended_reason", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organisations", "suspended_reason")
    op.drop_column("organisations", "suspended_at")
    op.drop_column("organisations", "status")

    op.drop_column("users", "suspended_reason")
    op.drop_column("users", "suspended_at")
    op.drop_column("users", "status")
