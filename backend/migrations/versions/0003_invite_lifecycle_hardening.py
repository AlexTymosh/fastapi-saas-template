"""invite lifecycle hardening

Revision ID: 0003_invite_lifecycle_hardening
Revises: 0002_add_user_org_statuses
Create Date: 2026-04-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_invite_lifecycle_hardening"
down_revision = "0002_add_user_org_statuses"
branch_labels = None
depends_on = None


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
    )


def downgrade() -> None:
    op.drop_index("uq_invites_org_email_pending", table_name="invites")
    op.drop_constraint(
        "fk_invites_revoked_by_user_id_users", "invites", type_="foreignkey"
    )
    op.drop_column("invites", "revoked_by_user_id")
    op.drop_column("invites", "revoked_at")
