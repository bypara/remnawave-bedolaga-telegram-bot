from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


def test_migration_0132_idempotent_upgrade_and_downgrade():
    root = Path(__file__).resolve().parents[2]
    module = ScriptDirectory.from_config(Config(str(root / 'alembic.ini'))).get_revision('0132').module
    engine = sa.create_engine('sqlite:///:memory:')
    try:
        with engine.begin() as conn:
            conn.execute(sa.text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
            context = MigrationContext.configure(conn)
            with Operations.context(context):
                module.upgrade()
                module.upgrade()
                inspector = sa.inspect(conn)
                assert inspector.get_pk_constraint('bot_migration_claims')['constrained_columns'] == ['user_id']
                assert inspector.get_unique_constraints('bot_migration_claims')[0]['column_names'] == ['token']
                assert len(inspector.get_columns('bot_migration_claims')) == 7
                module.downgrade()
                assert 'bot_migration_claims' not in sa.inspect(conn).get_table_names()
    finally:
        engine.dispose()
