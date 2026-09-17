import ast
import asyncio
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram import Bot
from aiogram.fsm.storage.base import StorageKey

from app.config import settings
from app.services.maintenance_service import MaintenanceService
from app.services.system_settings_service import BotConfigurationService


TEST_TOKEN = '456:test-token'


@pytest.fixture(autouse=True)
def support_minimal_redis_test_stub(monkeypatch):
    """Use real aiogram storage/key builders with conftest's fake Redis client."""
    import sys

    if 'redis.asyncio.client' not in sys.modules:
        client_module = ModuleType('redis.asyncio.client')
        client_module.Redis = sys.modules['redis.asyncio'].Redis
        lock_module = ModuleType('redis.asyncio.lock')
        lock_module.Lock = Mock
        connection_module = ModuleType('redis.asyncio.connection')
        connection_module.ConnectionPool = Mock
        typing_module = ModuleType('redis.typing')
        typing_module.ExpiryT = int
        monkeypatch.setitem(sys.modules, client_module.__name__, client_module)
        monkeypatch.setitem(sys.modules, lock_module.__name__, lock_module)
        monkeypatch.setitem(sys.modules, connection_module.__name__, connection_module)
        monkeypatch.setitem(sys.modules, typing_module.__name__, typing_module)


@pytest.mark.parametrize('primary', [True, False])
async def test_setup_starts_hidden_workers_and_admin_handlers_only_in_primary(monkeypatch, primary):
    from app import bot as bot_module
    from app.services.remnawave_retry_queue import remnawave_retry_queue

    monkeypatch.setattr(settings, 'BOT_PROCESS_ROLE', 'primary' if primary else 'interactive')
    monkeypatch.setattr(settings, 'MAIN_MENU_MODE', 'classic')
    monkeypatch.setattr(settings, 'MAINTENANCE_MODE', False)
    monkeypatch.setattr(type(settings), 'is_maintenance_monitoring_enabled', lambda _self: True)
    monkeypatch.setattr(bot_module.cache, 'connect', AsyncMock())
    monkeypatch.setattr('app.utils.bot_identity.sync_bot_username', AsyncMock())
    redis = SimpleNamespace(ping=AsyncMock(), aclose=AsyncMock())
    monkeypatch.setattr(bot_module, 'create_redis', lambda: redis)
    maintenance_start = AsyncMock()
    retry_start = AsyncMock()
    admin_register = Mock()
    monkeypatch.setattr(bot_module.maintenance_service, 'start_monitoring', maintenance_start)
    monkeypatch.setattr(remnawave_retry_queue, 'start', retry_start)
    monkeypatch.setattr(bot_module.admin_main, 'register_handlers', admin_register)
    bot = Bot(TEST_TOKEN)
    dp = None
    try:
        _, dp = await bot_module.setup_bot(bot=bot)
        assert bool(maintenance_start.await_count) is primary
        assert bool(retry_start.await_count) is primary
        assert bool(admin_register.call_count) is primary
        key = dp.storage.key_builder.build(StorageKey(bot_id=456, chat_id=42, user_id=42), 'state')
        if primary:
            assert key == 'fsm:42:42:state'
        else:
            assert key == 'fsm-interactive:456:42:42:state'
            other = dp.storage.key_builder.build(StorageKey(bot_id=789, chat_id=42, user_id=42), 'state')
            assert key != other
    finally:
        if dp:
            await dp.storage.close()
            # Production creates one dispatcher per process; parametrized tests
            # must release module-level routers before constructing another.
            for router in dp.sub_routers:
                router._parent_router = None
        await bot.session.close()


async def test_interactive_setup_refuses_redis_failure(monkeypatch):
    from app import bot as bot_module

    monkeypatch.setattr(settings, 'BOT_PROCESS_ROLE', 'interactive')
    monkeypatch.setattr(bot_module.cache, 'connect', AsyncMock())
    monkeypatch.setattr('app.utils.bot_identity.sync_bot_username', AsyncMock())
    redis = SimpleNamespace(ping=AsyncMock(side_effect=OSError('offline')), aclose=AsyncMock())
    monkeypatch.setattr(bot_module, 'create_redis', lambda: redis)
    bot = Bot(TEST_TOKEN)
    try:
        with pytest.raises(RuntimeError, match='Redis'):
            await bot_module.setup_bot(bot=bot)
        redis.aclose.assert_awaited_once()
    finally:
        await bot.session.close()


async def test_interactive_maintenance_bind_does_not_schedule_notifications(monkeypatch):
    monkeypatch.setattr(settings, 'BOT_PROCESS_ROLE', 'interactive')
    monkeypatch.setattr(settings, 'MAINTENANCE_MODE', True)
    service = MaintenanceService()
    enable = AsyncMock()
    monkeypatch.setattr(service, 'enable_maintenance', enable)
    service.set_bot(SimpleNamespace())
    await asyncio.sleep(0)
    enable.assert_not_awaited()
    assert service._check_task is None


async def test_passive_maintenance_follow_primary_and_manual_off(monkeypatch):
    from app.services.maintenance_service import cache

    monkeypatch.setattr(settings, 'MAINTENANCE_MODE', True)
    monkeypatch.setattr(cache, 'get', AsyncMock(return_value=None))
    service = MaintenanceService()
    await service.refresh_passive_status()
    assert service.is_maintenance_active()
    monkeypatch.setattr(settings, 'MAINTENANCE_MODE', False)
    await service.refresh_passive_status()
    assert not service.is_maintenance_active()
    cache.get.return_value = {'is_active': True, 'auto_enabled': True}
    await service.refresh_passive_status()
    assert service.is_maintenance_active()
    assert service.status.auto_enabled


@pytest.mark.parametrize('key,value', [('REMNAWAVE_AUTO_SYNC_ENABLED', True), ('BACKUP_AUTO_ENABLED', True)])
def test_worker_apply_hooks_disabled_for_interactive_role(monkeypatch, key, value):
    import sys

    monkeypatch.setattr(settings, 'BOT_PROCESS_ROLE', 'interactive')
    monkeypatch.setattr(BotConfigurationService, '_is_env_override', lambda _key: False)
    sync = Mock()
    backup = Mock()
    sync_module = ModuleType('app.services.remnawave_sync_service')
    sync_module.remnawave_sync_service = sync
    backup_module = ModuleType('app.services.backup_service')
    backup_module.backup_service = backup
    monkeypatch.setitem(sys.modules, sync_module.__name__, sync_module)
    monkeypatch.setitem(sys.modules, backup_module.__name__, backup_module)
    monkeypatch.setattr(settings, key, getattr(settings, key))
    BotConfigurationService._apply_to_settings(key, value)
    assert getattr(settings, key) == value
    sync.schedule_refresh.assert_not_called()
    backup.reload_settings_from_db.assert_not_called()


def test_main_checks_primary_role_before_any_startup_side_effect():
    module = ast.parse((Path(__file__).parents[2] / 'main.py').read_text(encoding='utf-8'))
    main = next(node for node in module.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'main')
    assert isinstance(main.body[0], ast.Expr)
    assert main.body[0].value.func.id == 'require_primary_process'


def test_interactive_main_menu_hides_admin_routes(monkeypatch):
    from app.keyboards.inline import get_main_menu_keyboard

    monkeypatch.setattr(settings, 'BOT_PROCESS_ROLE', 'interactive')
    monkeypatch.setattr(settings, 'MAIN_MENU_MODE', 'classic')
    keyboard = get_main_menu_keyboard(is_admin=True)
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert 'admin_panel' not in callbacks
