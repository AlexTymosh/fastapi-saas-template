"""invite lifecycle hardening

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "invites", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("invites", sa.Column("revoked_by_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_invites_revoked_by_user_id_users",
        "invites",
        "users",
        ["revoked_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_invites_org_email_pending",
        "invites",
        [sa.text("organisation_id"), sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_invites_org_email_pending", table_name="invites")
    op.drop_constraint(
        "fk_invites_revoked_by_user_id_users", "invites", type_="foreignkey"
    )
    op.drop_column("invites", "revoked_by_user_id")
    op.drop_column("invites", "revoked_at")
