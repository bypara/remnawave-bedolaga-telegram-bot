"""Read shared settings before imports construct integration singletons."""

from sqlalchemy import inspect

from app.database.database import engine


async def preload_database_settings() -> bool:
    # On a fresh database main.py still owns migrations/bootstrap. Other DB
    # failures must propagate: starting with defaults could disable payments.
    async with engine.connect() as connection:
        exists = await connection.run_sync(lambda conn: inspect(conn).has_table('system_settings'))
    if not exists:
        return False

    from app.migration_bot import RelaySettingsLoader

    # This reader parses every row before publishing and never invokes setters,
    # token bootstrap, sync/backup hooks, schedulers or Telegram transport.
    await RelaySettingsLoader().reload()
    return True
