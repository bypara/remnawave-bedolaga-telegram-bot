"""Fresh installs and migration upgrades must create the same Anore table."""

import importlib.util
import pathlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.database.models import AnorePayment, Base


VERSIONS = pathlib.Path(__file__).resolve().parents[2] / 'migrations/alembic/versions'
MIGRATION = '0134_create_anore_payments.py'
TABLE = 'anore_payments'


def _load_migration():
    spec = importlib.util.spec_from_file_location('m0134', VERSIONS / MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _referenced_tables(conn) -> None:
    conn.execute(sa.text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
    conn.execute(sa.text('CREATE TABLE transactions (id INTEGER PRIMARY KEY)'))


def _fresh(path: pathlib.Path):
    engine = sa.create_engine(f'sqlite:///{path}')
    with engine.begin() as conn:
        _referenced_tables(conn)
    Base.metadata.create_all(engine, tables=[AnorePayment.__table__])
    return engine


def _upgraded(path: pathlib.Path):
    engine = sa.create_engine(f'sqlite:///{path}')
    with engine.begin() as conn:
        _referenced_tables(conn)
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            _load_migration().upgrade()
    return engine


@pytest.fixture
def both(tmp_path):
    return sa.inspect(_fresh(tmp_path / 'fresh.db')), sa.inspect(_upgraded(tmp_path / 'upgraded.db'))


def test_columns_indexes_and_foreign_keys_match(both) -> None:
    fresh, upgraded = both
    assert {c['name'] for c in fresh.get_columns(TABLE)} == {c['name'] for c in upgraded.get_columns(TABLE)}
    assert {i['name'] for i in fresh.get_indexes(TABLE)} == {i['name'] for i in upgraded.get_indexes(TABLE)}
    assert {tuple(fk['constrained_columns']) for fk in fresh.get_foreign_keys(TABLE)} == {
        tuple(fk['constrained_columns']) for fk in upgraded.get_foreign_keys(TABLE)
    }


def test_unique_provider_and_order_ids_match(both) -> None:
    for inspector in both:
        unique = {tuple(i['column_names']) for i in inspector.get_indexes(TABLE) if i.get('unique')}
        unique |= {tuple(c['column_names']) for c in inspector.get_unique_constraints(TABLE)}
        assert ('order_id',) in unique
        assert ('anore_payment_id',) in unique


def test_downgrade_removes_table(tmp_path) -> None:
    engine = _upgraded(tmp_path / 'roundtrip.db')
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            _load_migration().downgrade()
    assert TABLE not in sa.inspect(engine).get_table_names()
