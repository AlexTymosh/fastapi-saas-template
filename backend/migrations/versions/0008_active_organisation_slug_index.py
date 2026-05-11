"""use active-only organisation slug uniqueness

Revision ID: 0008
Revises: 0007_add_one_active_owner_index
Create Date: 2026-05-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007_add_one_active_owner_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("organisations") as batch_op:
        batch_op.drop_constraint("uq_organisations_slug", type_="unique")

    op.create_index(
        "uq_organisations_slug_active",
        "organisations",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    duplicate_slugs = bind.execute(
        sa.text(
            """
            SELECT slug
            FROM organisations
            GROUP BY slug
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate_slugs is not None:
        raise RuntimeError(
            "Cannot downgrade safely: organisations contains duplicate slugs after "
            "active-only slug reuse. Rename or remove duplicate rows before "
            "restoring global slug uniqueness."
        )

    op.drop_index("uq_organisations_slug_active", table_name="organisations")

    with op.batch_alter_table("organisations") as batch_op:
        batch_op.create_unique_constraint("uq_organisations_slug", ["slug"])
