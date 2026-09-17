import ast
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import settings_bootstrap as bootstrap
from app.migration_bot import RelaySettingsLoader


def connection_factory(exists):
    connection = SimpleNamespace(run_sync=AsyncMock(return_value=exists))

    @asynccontextmanager
    async def connect():
        yield connection

    return SimpleNamespace(connect=connect)


async def test_existing_database_preloaded_readonly_before_integration_imports(monkeypatch):
    monkeypatch.setattr(bootstrap, 'engine', connection_factory(True))
    reload = AsyncMock()
    monkeypatch.setattr(RelaySettingsLoader, 'reload', reload)
    apply = Mock()
    from app.services.system_settings_service import BotConfigurationService

    monkeypatch.setattr(BotConfigurationService, '_apply_to_settings', apply)
    assert await bootstrap.preload_database_settings() is True
    reload.assert_awaited_once()
    apply.assert_not_called()


async def test_fresh_database_leaves_schema_bootstrap_to_main(monkeypatch):
    monkeypatch.setattr(bootstrap, 'engine', connection_factory(False))
    reload = AsyncMock()
    monkeypatch.setattr(RelaySettingsLoader, 'reload', reload)
    assert await bootstrap.preload_database_settings() is False
    reload.assert_not_awaited()


async def test_unreachable_database_does_not_fall_back_to_integration_defaults(monkeypatch):
    @asynccontextmanager
    async def connect():
        raise OSError('offline')
        yield  # pragma: no cover

    monkeypatch.setattr(bootstrap, 'engine', SimpleNamespace(connect=connect))
    with pytest.raises(OSError, match='offline'):
        await bootstrap.preload_database_settings()


async def test_invalid_database_settings_abort_before_importing_integrations(monkeypatch):
    monkeypatch.setattr(bootstrap, 'engine', connection_factory(True))
    monkeypatch.setattr(RelaySettingsLoader, 'reload', AsyncMock(side_effect=ValueError('invalid config')))
    with pytest.raises(ValueError, match='invalid config'):
        await bootstrap.preload_database_settings()


def test_main_loads_database_before_any_business_service_import():
    module = ast.parse((Path(__file__).parents[2] / 'main.py').read_text(encoding='utf-8'))
    for node in module.body:
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or '').startswith(('app.services.', 'app.bot', 'app.webserver.'))
    main = next(node for node in module.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'main')
    assert main.body[0].value.func.id == 'require_primary_process'
    assert isinstance(main.body[1].value, ast.Await)
    assert main.body[1].value.value.func.id == 'preload_database_settings'
    service_imports = [index for index, node in enumerate(main.body) if isinstance(node, ast.ImportFrom)]
    assert min(service_imports) > 1
