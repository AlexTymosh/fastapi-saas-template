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


_OLD_URL_ISSUANCE_BACKFILL = """
UPDATE export_artifacts
SET
    download_url_issued_at = downloaded_at,
    download_url_issue_count = download_count,
    downloaded_at = NULL,
    download_count = 0
WHERE downloaded_at IS NOT NULL OR download_count > 0
"""

_RESET_LEGACY_DELIVERED_EXPORTS = """
UPDATE data_subject_requests
SET execution_status = 'ready'
WHERE request_type = 'export'
  AND execution_status = 'delivered'
  AND EXISTS (
      SELECT 1
      FROM export_artifacts
      WHERE export_artifacts.data_subject_request_id = data_subject_requests.id
        AND export_artifacts.status = 'ready'
  )
"""

_DOWNGRADE_URL_ISSUANCE_TO_LEGACY_DOWNLOADS = """
UPDATE export_artifacts
SET
    downloaded_at = download_url_issued_at,
    download_count = download_url_issue_count
WHERE download_url_issued_at IS NOT NULL OR download_url_issue_count > 0
"""


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

    op.execute(sa.text(_OLD_URL_ISSUANCE_BACKFILL))
    op.execute(sa.text(_RESET_LEGACY_DELIVERED_EXPORTS))


def downgrade() -> None:
    op.execute(sa.text(_DOWNGRADE_URL_ISSUANCE_TO_LEGACY_DOWNLOADS))

    with op.batch_alter_table("export_artifacts") as batch_op:
        batch_op.drop_column("download_url_issue_count")
        batch_op.drop_column("download_url_issued_at")
