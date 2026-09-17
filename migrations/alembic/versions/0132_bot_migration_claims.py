"""Personal migration links and one-time bonus claims.

Revision ID: 0132
Revises: 0131
"""

import sqlalchemy as sa
from alembic import op


revision = '0132'
down_revision = '0131'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if 'bot_migration_claims' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        'bot_migration_claims',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('token', sa.String(43), nullable=False, unique=True),
        sa.Column('source_bot_id', sa.BigInteger(), nullable=False),
        sa.Column('target_bot_username', sa.String(32), nullable=False),
        sa.Column('amount_kopeks', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('amount_kopeks > 0', name='ck_bot_migration_claim_positive'),
    )


def downgrade() -> None:
    if 'bot_migration_claims' in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table('bot_migration_claims')
