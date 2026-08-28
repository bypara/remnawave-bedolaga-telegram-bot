"""subscriptions: snapshots of applied tariff limits

Revision ID: 0108
Revises: 0107
Create Date: 2026-08-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0108'
down_revision: Union[str, None] = '0107'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'subscriptions' not in inspector.get_table_names():
        return

    existing = {col['name'] for col in inspector.get_columns('subscriptions')}
    if 'applied_tariff_traffic_gb' not in existing:
        op.add_column('subscriptions', sa.Column('applied_tariff_traffic_gb', sa.Integer(), nullable=True))
    if 'applied_tariff_device_limit' not in existing:
        op.add_column('subscriptions', sa.Column('applied_tariff_device_limit', sa.Integer(), nullable=True))

    # The current tariff values are the safest baseline for legacy rows. If a
    # subscription is already above that base, the difference is deliberately
    # treated as a possible paid add-on and is never removed automatically.
    op.execute(
        sa.text(
            """
            UPDATE subscriptions
            SET applied_tariff_traffic_gb = (
                    SELECT tariffs.traffic_limit_gb FROM tariffs WHERE tariffs.id = subscriptions.tariff_id
                ),
                applied_tariff_device_limit = (
                    SELECT tariffs.device_limit FROM tariffs WHERE tariffs.id = subscriptions.tariff_id
                )
            WHERE tariff_id IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'subscriptions' not in inspector.get_table_names():
        return
    existing = {col['name'] for col in inspector.get_columns('subscriptions')}
    if 'applied_tariff_device_limit' in existing:
        op.drop_column('subscriptions', 'applied_tariff_device_limit')
    if 'applied_tariff_traffic_gb' in existing:
        op.drop_column('subscriptions', 'applied_tariff_traffic_gb')
