"""user projection and membership role updates

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("keycloak_id", new_column_name="external_auth_id")
        batch_op.alter_column(
            "external_auth_id", existing_type=sa.String(length=255), nullable=False
        )
        batch_op.add_column(
            sa.Column(
                "email_verified",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch_op.add_column(
            sa.Column("first_name", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column("last_name", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "onboarding_completed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )

    op.execute(
        "UPDATE memberships SET role = 'member' "
        "WHERE role NOT IN ('owner', 'admin', 'member')"
    )

    with op.batch_alter_table("memberships") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=sa.Enum(
                "owner", "member", name="membership_role", native_enum=False
            ),
            type_=sa.Enum(
                "owner",
                "admin",
                "member",
                name="membership_role",
                native_enum=False,
            ),
            existing_nullable=False,
            server_default="member",
        )


def downgrade() -> None:
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=sa.Enum(
                "owner",
                "admin",
                "member",
                name="membership_role",
                native_enum=False,
            ),
            type_=sa.Enum("owner", "member", name="membership_role", native_enum=False),
            existing_nullable=False,
            server_default="member",
        )

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("onboarding_completed")
        batch_op.drop_column("last_name")
        batch_op.drop_column("first_name")
        batch_op.drop_column("email_verified")
        batch_op.alter_column(
            "external_auth_id", existing_type=sa.String(length=255), nullable=True
        )
        batch_op.alter_column("external_auth_id", new_column_name="keycloak_id")
