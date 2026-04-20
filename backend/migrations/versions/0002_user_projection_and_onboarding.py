"""user projection and onboarding fields

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


old_membership_role = sa.Enum(
    "owner",
    "member",
    name="membership_role",
    native_enum=False,
)
new_membership_role = sa.Enum(
    "owner",
    "admin",
    "member",
    name="membership_role",
    native_enum=False,
)


def upgrade() -> None:
    op.alter_column("users", "keycloak_id", new_column_name="external_auth_id")

    connection = op.get_bind()
    null_external_auth_ids = connection.execute(
        sa.text("SELECT COUNT(*) FROM users WHERE external_auth_id IS NULL")
    ).scalar_one()

    if null_external_auth_ids:
        raise RuntimeError(
            "Migration 0002 aborted: users.external_auth_id contains NULL values. "
            "Backfill external_auth_id before applying this migration."
        )

    op.alter_column(
        "users",
        "external_auth_id",
        existing_type=sa.String(length=255),
        nullable=False,
    )

    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("first_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("last_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "onboarding_completed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    with op.batch_alter_table("memberships") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=old_membership_role,
            type_=new_membership_role,
        )


def downgrade() -> None:
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=new_membership_role,
            type_=old_membership_role,
        )

    op.drop_column("users", "onboarding_completed")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
    op.drop_column("users", "email_verified")

    op.alter_column(
        "users",
        "external_auth_id",
        existing_type=sa.String(length=255),
        nullable=True,
    )
    op.alter_column("users", "external_auth_id", new_column_name="keycloak_id")
