import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_upgrade_preserves_history_is_idempotent_and_can_downgrade():
    path = Path(__file__).parents[2] / 'migrations/alembic/versions/0133_broadcast_legacy_sender.py'
    spec = importlib.util.spec_from_file_location('legacy_sender_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(sa.text('CREATE TABLE broadcast_history (id INTEGER PRIMARY KEY)'))
        conn.execute(sa.text('INSERT INTO broadcast_history (id) VALUES (42)'))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
            module.upgrade()
            row = conn.execute(sa.text('SELECT id, telegram_sender, add_migration_button FROM broadcast_history')).one()
            assert tuple(row) == (42, 'current', 0)
            module.downgrade()
        assert conn.execute(sa.text('SELECT id FROM broadcast_history')).scalar_one() == 42
        assert [column['name'] for column in sa.inspect(conn).get_columns('broadcast_history')] == ['id']
    engine.dispose()
