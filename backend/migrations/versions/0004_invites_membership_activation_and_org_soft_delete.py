"""add invites and active membership transfer support

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-21 00:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.add_column(
            sa.Column(
                "active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
        batch_op.drop_constraint("uq_memberships_user_id", type_="unique")

    op.create_index(
        "ix_memberships_active_user_unique",
        "memberships",
        ["user_id"],
        unique=True,
        sqlite_where=sa.text("active = 1"),
        postgresql_where=sa.text("active = true"),
    )

    with op.batch_alter_table("organisations") as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "invites",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("owner", "admin", "member", name="invite_role", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "accepted", "expired", name="invite_status", native_enum=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invites")),
        sa.UniqueConstraint("token", name="uq_invites_token"),
    )
    op.create_index(op.f("ix_invites_email"), "invites", ["email"], unique=False)
    op.create_index(
        op.f("ix_invites_organisation_id"),
        "invites",
        ["organisation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_invites_organisation_id"), table_name="invites")
    op.drop_index(op.f("ix_invites_email"), table_name="invites")
    op.drop_table("invites")

    with op.batch_alter_table("organisations") as batch_op:
        batch_op.drop_column("deleted_at")

    op.drop_index("ix_memberships_active_user_unique", table_name="memberships")
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.create_unique_constraint("uq_memberships_user_id", ["user_id"])
        batch_op.drop_column("active")
