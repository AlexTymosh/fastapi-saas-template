"""add audit events

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "category",
            sa.Enum(
                "tenant",
                "platform",
                "security",
                "compliance",
                name="audit_category",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "action",
            sa.Enum(
                "organisation_updated",
                "organisation_deleted",
                "membership_role_changed",
                "membership_removed",
                "invite_revoked",
                "invite_resent",
                name="audit_action",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"], unique=False
    )
    op.create_index(
        "ix_audit_events_category", "audit_events", ["category"], unique=False
    )
    op.create_index("ix_audit_events_action", "audit_events", ["action"], unique=False)
    op.create_index(
        "ix_audit_events_target",
        "audit_events",
        ["target_type", "target_id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_created_at", "audit_events", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_target", table_name="audit_events")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_category", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_table("audit_events")
