"""add one active owner per organisation index

Revision ID: 0007_add_one_active_owner_index
Revises: 0006_add_outbox_events
Create Date: 2026-05-02
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0007_add_one_active_owner_index"
down_revision = "0006_add_outbox_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_memberships_one_active_owner_per_org",
        "memberships",
        ["organisation_id"],
        unique=True,
        postgresql_where="role = 'owner' AND is_active = true",
        sqlite_where="role = 'owner' AND is_active = 1",
    )


def downgrade() -> None:
    op.drop_index("uq_memberships_one_active_owner_per_org", table_name="memberships")
