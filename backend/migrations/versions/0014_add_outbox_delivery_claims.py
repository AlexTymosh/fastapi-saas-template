"""add outbox delivery claims

Revision ID: 0014_outbox_delivery_claims
Revises: 0013_dsr_exec_state
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_outbox_delivery_claims"
down_revision: str | None = "0013_dsr_exec_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox_delivery_claims",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("claim_token", sa.String(length=64), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["outbox_events.id"],
            name=op.f("fk_outbox_delivery_claims_event_id_outbox_events"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "event_id",
            name=op.f("pk_outbox_delivery_claims"),
        ),
    )
    op.create_index(
        "ix_outbox_delivery_claims_claim_token",
        "outbox_delivery_claims",
        ["claim_token"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbox_delivery_claims_claim_token",
        table_name="outbox_delivery_claims",
    )
    op.drop_table("outbox_delivery_claims")
