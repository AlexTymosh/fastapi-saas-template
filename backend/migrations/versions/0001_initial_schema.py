"""create initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

membership_role = sa.Enum(
    "owner",
    "admin",
    "member",
    name="membership_role",
    native_enum=False,
)

invite_status = sa.Enum(
    "pending",
    "accepted",
    "expired",
    name="invite_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "organisations",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organisations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organisations_slug")),
    )

    op.create_table(
        "users",
        sa.Column("external_auth_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column(
            "onboarding_completed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("external_auth_id", name=op.f("uq_users_external_auth_id")),
    )

    op.create_table(
        "memberships",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            membership_role,
            nullable=False,
            server_default="member",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
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
            name=op.f("fk_memberships_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_memberships_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
    )

    op.create_index(
        op.f("ix_memberships_user_id"), "memberships", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_memberships_organisation_id"),
        "memberships",
        ["organisation_id"],
        unique=False,
    )
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
        sa.Column("role", membership_role, nullable=False, server_default="member"),
        sa.Column("status", invite_status, nullable=False, server_default="pending"),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(op.f("ix_invites_email"), "invites", ["email"], unique=False)
    op.create_index(
        op.f("ix_invites_organisation_id"),
        "invites",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_invites_token_hash"), "invites", ["token_hash"], unique=True
    )
    op.create_index(
        op.f("ix_invites_expires_at"), "invites", ["expires_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_invites_expires_at"), table_name="invites")
    op.drop_index(op.f("ix_invites_token_hash"), table_name="invites")
    op.drop_index(op.f("ix_invites_organisation_id"), table_name="invites")
    op.drop_index(op.f("ix_invites_email"), table_name="invites")
    op.drop_table("invites")

    op.drop_index("uq_memberships_user_id_active", table_name="memberships")
    op.drop_index(op.f("ix_memberships_organisation_id"), table_name="memberships")
    op.drop_index(op.f("ix_memberships_user_id"), table_name="memberships")
    op.drop_table("memberships")

    op.drop_table("users")
    op.drop_table("organisations")
