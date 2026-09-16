"""Upgrade our existing 0126 database through the incoming upstream migrations."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from tests.fixtures.postgres_db import postgres_engine


ROOT = Path(__file__).resolve().parents[2]


def _check_upgrade(conn):
    conn.execute(sa.text('CREATE TABLE tariffs (id INTEGER PRIMARY KEY, name VARCHAR(255))'))
    conn.execute(sa.text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
    conn.execute(sa.text('CREATE TABLE subscriptions (id INTEGER PRIMARY KEY)'))
    conn.execute(
        sa.text(
            'CREATE TABLE grace_access_sessions '
            '(subscription_id INTEGER, state VARCHAR(32), overlay JSON, started_at TIMESTAMP)'
        )
    )
    conn.execute(sa.text('INSERT INTO subscriptions (id) VALUES (1), (2), (3), (4)'))
    rows = [
        (1, 'active', '2026-09-17T01:00:00Z', '2026-09-16T01:00:00'),
        (1, 'active', '2026-09-18T01:00:00Z', '2026-09-17T01:00:00'),
        (2, 'closed', '2026-09-19T01:00:00Z', '2026-09-17T01:00:00'),
        (3, 'pending', '2026-09-20T01:00:00Z', '2026-09-17T01:00:00'),
        (4, 'restoring', '2026-09-21T01:00:00Z', '2026-09-17T01:00:00'),
    ]
    for sub_id, state, expires, started in rows:
        conn.execute(
            sa.text('INSERT INTO grace_access_sessions VALUES (:sub_id, :state, :overlay, :started)'),
            {
                'sub_id': sub_id,
                'state': state,
                'overlay': json.dumps({'expire_at': expires}),
                'started': datetime.fromisoformat(started),
            },
        )
    script = ScriptDirectory.from_config(Config(str(ROOT / 'alembic.ini')))
    revisions = list(reversed(list(script.iterate_revisions('head', '0126'))))
    assert [rev.revision for rev in revisions] == ['0127', '0128', '0129', '0130', '0131']
    with Operations.context(MigrationContext.configure(conn)):
        for revision in revisions:
            revision.module.upgrade()
        # Existing columns must also be handled safely on a repeated invocation.
        for revision in revisions:
            revision.module.upgrade()

    inspector = sa.inspect(conn)
    assert {'panel_tag', 'trial_duration_days'} <= {col['name'] for col in inspector.get_columns('tariffs')}
    assert 'trial_reset_at' in {col['name'] for col in inspector.get_columns('users')}
    result = conn.execute(sa.text('SELECT id, grace_session_open FROM subscriptions ORDER BY id')).all()
    assert [(sub_id, bool(is_open)) for sub_id, is_open in result] == [(1, True), (2, False), (3, True), (4, True)]
    value = conn.execute(sa.text('SELECT grace_overlay_expire_at FROM subscriptions WHERE id = 1')).scalar_one()
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    assert value.replace(tzinfo=UTC) == datetime(2026, 9, 18, 1, tzinfo=UTC)


def test_existing_database_upgrade_sqlite():
    engine = sa.create_engine('sqlite:///:memory:')
    try:
        with engine.begin() as conn:
            _check_upgrade(conn)
    finally:
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_existing_database_upgrade_postgres(postgres_database):
    async with postgres_engine(postgres_database) as engine:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            try:
                # Transaction-local schema: no application tables are changed.
                await conn.execute(sa.text('CREATE SCHEMA codex_upstream_migration_check'))
                await conn.execute(sa.text('SET LOCAL search_path = codex_upstream_migration_check'))
                await conn.run_sync(_check_upgrade)
            finally:
                await transaction.rollback()
