"""invite lifecycle hardening

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-29 00:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("invites") as batch_op:
        batch_op.add_column(
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("revoked_by_user_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_invites_revoked_by_user_id_users",
            "users",
            ["revoked_by_user_id"],
            ["id"],
        )
        batch_op.drop_constraint("invite_status", type_="check")
        batch_op.create_check_constraint(
            "invite_status",
            "status IN ('pending', 'accepted', 'expired', 'revoked')",
        )

    op.create_index(
        "uq_invites_pending_email_per_org",
        "invites",
        [sa.text("organisation_id"), sa.text("lower(email)")],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_invites_pending_email_per_org", table_name="invites")
    with op.batch_alter_table("invites") as batch_op:
        batch_op.drop_constraint("invite_status", type_="check")
        batch_op.create_check_constraint(
            "invite_status",
            "status IN ('pending', 'accepted', 'expired')",
        )
        batch_op.drop_constraint(
            "fk_invites_revoked_by_user_id_users", type_="foreignkey"
        )
        batch_op.drop_column("revoked_by_user_id")
        batch_op.drop_column("revoked_at")
