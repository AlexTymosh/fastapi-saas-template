"""add platform staff

Revision ID: 0005_add_platform_staff
Revises: 0004_add_audit_events
"""
from alembic import op
import sqlalchemy as sa

revision = '0005_add_platform_staff'
down_revision = '0004_add_audit_events'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'platform_staff',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('role', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('created_by_user_id', sa.UUID(), nullable=True),
        sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('suspended_reason', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('platform_admin', 'support_agent', 'compliance_officer')", name='ck_platform_staff_role'),
        sa.CheckConstraint("status IN ('active', 'suspended')", name='ck_platform_staff_status'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )
    op.create_index('ix_platform_staff_role', 'platform_staff', ['role'])
    op.create_index('ix_platform_staff_status', 'platform_staff', ['status'])


def downgrade() -> None:
    op.drop_index('ix_platform_staff_status', table_name='platform_staff')
    op.drop_index('ix_platform_staff_role', table_name='platform_staff')
    op.drop_table('platform_staff')
