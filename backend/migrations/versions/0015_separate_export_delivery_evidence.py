"""separate export URL issuance from delivery evidence

Revision ID: 0015_export_delivery_evidence
Revises: 0014_outbox_delivery_claims
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_export_delivery_evidence"
down_revision: str | None = "0014_outbox_delivery_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("export_artifacts") as batch_op:
        batch_op.add_column(
            sa.Column("download_url_issued_at", sa.DateTime(timezone=True))
        )
        batch_op.add_column(
            sa.Column(
                "download_url_issue_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("export_artifacts") as batch_op:
        batch_op.drop_column("download_url_issue_count")
        batch_op.drop_column("download_url_issued_at")
