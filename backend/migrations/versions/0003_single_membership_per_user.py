"""enforce single-organisation membership per user

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-21 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicate_users = (
        connection.execute(
            sa.text(
                """
            SELECT user_id, COUNT(*) AS membership_count
            FROM memberships
            GROUP BY user_id
            HAVING COUNT(*) > 1
            ORDER BY membership_count DESC, user_id
            LIMIT 1
            """
            )
        )
        .mappings()
        .first()
    )

    if duplicate_users is not None:
        raise RuntimeError(
            "Migration 0003 cannot proceed: memberships contain users with more "
            "than one organisation membership. Resolve duplicate memberships "
            "before retrying."
        )

    with op.batch_alter_table("memberships") as batch_op:
        batch_op.drop_constraint(
            "uq_memberships_user_id_organisation_id",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_memberships_user_id",
            ["user_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.drop_constraint("uq_memberships_user_id", type_="unique")
        batch_op.create_unique_constraint(
            "uq_memberships_user_id_organisation_id",
            ["user_id", "organisation_id"],
        )
