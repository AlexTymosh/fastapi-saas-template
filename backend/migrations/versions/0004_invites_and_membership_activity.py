"""add invites and active membership model

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-21 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


invite_status = sa.Enum(
    "pending",
    "accepted",
    "expired",
    name="invite_status",
    native_enum=False,
)


def upgrade() -> None:
    op.add_column(
        "organisations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "memberships",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.drop_constraint("uq_memberships_user_id", type_="unique")

    op.create_index(
        "uq_memberships_user_id_active",
        "memberships",
        ["user_id"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active = true"),
    )

    op.create_table(
        "invites",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("owner", "admin", "member", name="membership_role", native_enum=False),
            nullable=False,
            server_default="member",
        ),
        sa.Column("status", invite_status, nullable=False, server_default="pending"),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_invites_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invites")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invites_token_hash")),
    )
    op.create_index(op.f("ix_invites_email"), "invites", ["email"], unique=False)
    op.create_index(
        op.f("ix_invites_organisation_id"), "invites", ["organisation_id"], unique=False
    )
    op.create_index(op.f("ix_invites_token_hash"), "invites", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_invites_token_hash"), table_name="invites")
    op.drop_index(op.f("ix_invites_organisation_id"), table_name="invites")
    op.drop_index(op.f("ix_invites_email"), table_name="invites")
    op.drop_table("invites")

    op.drop_index("uq_memberships_user_id_active", table_name="memberships")
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.create_unique_constraint("uq_memberships_user_id", ["user_id"])
    op.drop_column("memberships", "is_active")

    op.drop_column("organisations", "deleted_at")
