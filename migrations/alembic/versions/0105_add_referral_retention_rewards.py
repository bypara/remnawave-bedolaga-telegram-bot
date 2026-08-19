"""add delayed referral retention rewards

Revision ID: 0105
Revises: 0104
Create Date: 2026-08-19
"""

import sqlalchemy as sa
from alembic import op


revision = '0105'
down_revision = '0104'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'referral_retention_rewards' in set(inspector.get_table_names()):
        return

    op.create_table(
        'referral_retention_rewards',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('referrer_id', sa.Integer(), nullable=False),
        sa.Column('referral_id', sa.Integer(), nullable=False),
        sa.Column('amount_kopeks', sa.Integer(), nullable=False),
        sa.Column('eligible_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['referral_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['referrer_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('referral_id', name='uq_referral_retention_rewards_referral_id'),
    )
    op.create_index('ix_referral_retention_rewards_id', 'referral_retention_rewards', ['id'])
    op.create_index('ix_referral_retention_rewards_referrer_id', 'referral_retention_rewards', ['referrer_id'])
    op.create_index('ix_referral_retention_rewards_referral_id', 'referral_retention_rewards', ['referral_id'])
    op.create_index('ix_referral_retention_due', 'referral_retention_rewards', ['status', 'eligible_at'])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'referral_retention_rewards' in set(inspector.get_table_names()):
        op.drop_table('referral_retention_rewards')
