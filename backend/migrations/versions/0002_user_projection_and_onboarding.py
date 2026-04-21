"""user projection, onboarding fields, and final user constraints

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-21 00:00:00.000000
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
    connection = op.get_bind()
    null_external_ids = connection.execute(
        sa.text("SELECT COUNT(*) FROM users WHERE keycloak_id IS NULL")
    ).scalar_one()
    if null_external_ids:
        raise RuntimeError(
            "Migration 0002 cannot proceed: users.keycloak_id contains NULL "
            "values. Backfill all user external identity values before retrying."
        )

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("keycloak_id", new_column_name="external_auth_id")
        batch_op.drop_constraint(op.f("uq_users_keycloak_id"), type_="unique")
        batch_op.drop_constraint(op.f("uq_users_email"), type_="unique")
        batch_op.alter_column(
            "external_auth_id",
            existing_type=sa.String(length=255),
            nullable=False,
        )
        batch_op.create_unique_constraint(
            op.f("uq_users_external_auth_id"),
            ["external_auth_id"],
        )
        batch_op.add_column(
            sa.Column(
                "email_verified",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch_op.add_column(sa.Column("first_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("last_name", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column(
                "onboarding_completed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )

    with op.batch_alter_table("memberships") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=old_membership_role,
            type_=new_membership_role,
        )


def downgrade() -> None:
    op.execute(sa.text("UPDATE memberships SET role = 'member' WHERE role = 'admin'"))

    with op.batch_alter_table("memberships") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=new_membership_role,
            type_=old_membership_role,
        )

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("onboarding_completed")
        batch_op.drop_column("last_name")
        batch_op.drop_column("first_name")
        batch_op.drop_column("email_verified")
        batch_op.drop_constraint(op.f("uq_users_external_auth_id"), type_="unique")
        batch_op.alter_column(
            "external_auth_id",
            existing_type=sa.String(length=255),
            nullable=True,
        )
        batch_op.alter_column("external_auth_id", new_column_name="keycloak_id")
        batch_op.create_unique_constraint(op.f("uq_users_keycloak_id"), ["keycloak_id"])
        batch_op.create_unique_constraint(op.f("uq_users_email"), ["email"])
