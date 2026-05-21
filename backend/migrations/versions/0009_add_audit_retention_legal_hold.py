"""add audit retention legal hold marker

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.add_column(
            sa.Column("legal_hold_until", sa.DateTime(timezone=True), nullable=True)
        )

    op.create_index(
        "ix_audit_events_legal_hold_until",
        "audit_events",
        ["legal_hold_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_legal_hold_until", table_name="audit_events")

    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_column("legal_hold_until")
