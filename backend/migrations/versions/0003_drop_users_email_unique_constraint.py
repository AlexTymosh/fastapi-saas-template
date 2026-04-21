"""drop users email unique constraint

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-21 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint(op.f("uq_users_email"), type_="unique")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.create_unique_constraint(op.f("uq_users_email"), ["email"])
