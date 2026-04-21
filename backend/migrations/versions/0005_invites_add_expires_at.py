"""add invite expiration timestamp

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-21 12:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "invites",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_invites_expires_at"), "invites", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_invites_expires_at"), table_name="invites")
    op.drop_column("invites", "expires_at")
