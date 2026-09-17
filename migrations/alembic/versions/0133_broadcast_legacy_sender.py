"""Record outbound bot selection and optional migration button in broadcast history."""

import sqlalchemy as sa
from alembic import op

revision = '0133'
down_revision = '0132'
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('broadcast_history')}
    if 'telegram_sender' not in columns:
        op.add_column(
            'broadcast_history', sa.Column('telegram_sender', sa.String(20), nullable=False, server_default='current')
        )
    if 'add_migration_button' not in columns:
        op.add_column(
            'broadcast_history',
            sa.Column('add_migration_button', sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    op.drop_column('broadcast_history', 'add_migration_button')
    op.drop_column('broadcast_history', 'telegram_sender')
