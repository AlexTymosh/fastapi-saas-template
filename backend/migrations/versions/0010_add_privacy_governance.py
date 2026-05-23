"""add privacy governance records

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LAWFUL_BASIS_VALUES = (
    "'consent', 'contract', 'legal_obligation', 'vital_interests', "
    "'public_task', 'legitimate_interests', 'recognised_legitimate_interests'"
)
_SPECIAL_CATEGORY_VALUES = (
    "'explicit_consent', 'employment_social_security_social_protection', "
    "'vital_interests', 'nonprofit_body', 'manifestly_public', "
    "'legal_claims', 'substantial_public_interest', 'regulated_service_provision', "
    "'public_interest_safeguarding', 'archiving_research_statistics'"
)
_PURPOSE_FAMILY_VALUES = (
    "'account', 'invite', 'audit', 'marketing', 'product_analytics', "
    "'regulated_service_delivery', 'legal_compliance'"
)


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "processing_purposes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("family", sa.String(length=64), nullable=False),
        sa.Column("default_lawful_basis", sa.String(length=64), nullable=False),
        sa.Column(
            "is_special_category",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "default_special_category_condition",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "requires_active_consent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        *_timestamp_columns(),
        sa.CheckConstraint(
            f"default_lawful_basis IN ({_LAWFUL_BASIS_VALUES})",
            name="ck_processing_purposes_default_lawful_basis_valid",
        ),
        sa.CheckConstraint(
            f"family IN ({_PURPOSE_FAMILY_VALUES})",
            name="ck_processing_purposes_family_valid",
        ),
        sa.CheckConstraint(
            "default_special_category_condition IS NULL "
            f"OR default_special_category_condition IN ({_SPECIAL_CATEGORY_VALUES})",
            name="ck_processing_purposes_special_category_condition_valid",
        ),
        sa.CheckConstraint(
            "NOT is_special_category OR default_special_category_condition IS NOT NULL",
            name="ck_processing_purposes_special_category_requires_condition",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_processing_purposes_code",
        "processing_purposes",
        ["code"],
        unique=True,
    )

    op.create_table(
        "data_processing_authorizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject_user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose_id", sa.Uuid(), nullable=False),
        sa.Column("lawful_basis", sa.String(length=64), nullable=False),
        sa.Column("special_category_condition", sa.String(length=100), nullable=True),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=True),
        *_timestamp_columns(),
        sa.CheckConstraint(
            f"lawful_basis IN ({_LAWFUL_BASIS_VALUES})",
            name="ck_data_processing_authorizations_lawful_basis_valid",
        ),
        sa.CheckConstraint(
            "special_category_condition IS NULL "
            f"OR special_category_condition IN ({_SPECIAL_CATEGORY_VALUES})",
            name="ck_data_processing_authorizations_special_condition_valid",
        ),
        sa.ForeignKeyConstraint(
            ["purpose_id"], ["processing_purposes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["subject_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_data_processing_authorizations_subject_purpose_active",
        "data_processing_authorizations",
        ["subject_user_id", "purpose_id", "active"],
    )
    op.create_index(
        "ix_data_processing_authorizations_valid_until",
        "data_processing_authorizations",
        ["valid_until"],
    )

    op.create_table(
        "consent_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject_user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=True),
        sa.Column("privacy_notice_version", sa.String(length=64), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawal_reason_code", sa.String(length=64), nullable=True),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["authorization_id"],
            ["data_processing_authorizations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["purpose_id"], ["processing_purposes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["subject_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_consent_records_authorization_id",
        "consent_records",
        ["authorization_id"],
    )
    op.create_index(
        "ix_consent_records_subject_purpose_withdrawn",
        "consent_records",
        ["subject_user_id", "purpose_id", "withdrawn_at"],
    )

    op.create_table(
        "privacy_notice_acceptances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject_user_id", sa.Uuid(), nullable=False),
        sa.Column("notice_version", sa.String(length=64), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=128), nullable=True),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["subject_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_privacy_notice_acceptances_subject_version",
        "privacy_notice_acceptances",
        ["subject_user_id", "notice_version"],
        unique=True,
    )
    op.create_index(
        "ix_privacy_notice_acceptances_accepted_at",
        "privacy_notice_acceptances",
        ["accepted_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_privacy_notice_acceptances_accepted_at",
        table_name="privacy_notice_acceptances",
    )
    op.drop_index(
        "uq_privacy_notice_acceptances_subject_version",
        table_name="privacy_notice_acceptances",
    )
    op.drop_table("privacy_notice_acceptances")

    op.drop_index(
        "ix_consent_records_subject_purpose_withdrawn",
        table_name="consent_records",
    )
    op.drop_index("ix_consent_records_authorization_id", table_name="consent_records")
    op.drop_table("consent_records")

    op.drop_index(
        "ix_data_processing_authorizations_valid_until",
        table_name="data_processing_authorizations",
    )
    op.drop_index(
        "ix_data_processing_authorizations_subject_purpose_active",
        table_name="data_processing_authorizations",
    )
    op.drop_table("data_processing_authorizations")

    op.drop_index("ix_processing_purposes_code", table_name="processing_purposes")
    op.drop_table("processing_purposes")
