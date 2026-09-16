"""Support settings stay shared by the bot and cabinet across DB initialization."""

import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.database.crud.system_setting import get_setting_value
from app.database.models import SystemSetting
from app.services.support_settings_service import SupportSettingsService
from app.services.system_settings_service import bot_configuration_service
from tests.fixtures.sqlite_memory import memory_session


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    bot_configuration_service.initialize_definitions()
    for key in ('SUPPORT_SYSTEM_MODE', 'SUPPORT_MENU_ENABLED'):
        monkeypatch.setattr(settings, key, getattr(settings, key))
    monkeypatch.setattr(bot_configuration_service, '_overrides_raw', {})
    monkeypatch.setattr(bot_configuration_service, '_env_override_keys', set())
    monkeypatch.setattr(SupportSettingsService, '_legacy_path', tmp_path / 'support_settings.json')


@pytest.mark.asyncio
async def test_support_mode_survives_db_initialization(monkeypatch):
    async with memory_session(monkeypatch, [SystemSetting.__table__]) as db:
        assert await SupportSettingsService.set_system_mode(db, 'contact')
        assert await SupportSettingsService.set_support_menu_enabled(db, False)
        maker = async_sessionmaker(db.bind, expire_on_commit=False)
        monkeypatch.setattr('app.services.system_settings_service.AsyncSessionLocal', maker)
        monkeypatch.setattr(settings, 'SUPPORT_SYSTEM_MODE', 'both')
        monkeypatch.setattr(settings, 'SUPPORT_MENU_ENABLED', True)
        bot_configuration_service._overrides_raw.clear()
        await bot_configuration_service.initialize(sync_web_api_token=False)
        assert SupportSettingsService.get_system_mode() == 'contact'
        assert settings.is_support_tickets_enabled() is False
        assert SupportSettingsService.is_support_menu_enabled() is False


@pytest.mark.asyncio
async def test_legacy_import_does_not_clobber_env_mode(monkeypatch):
    legacy = SupportSettingsService._legacy_path
    legacy.write_text(json.dumps({'system_mode': 'tickets'}), encoding='utf-8')
    monkeypatch.setattr(settings, 'SUPPORT_SYSTEM_MODE', 'both')
    monkeypatch.setattr(bot_configuration_service, '_env_override_keys', {'SUPPORT_SYSTEM_MODE'})
    async with memory_session(monkeypatch, [SystemSetting.__table__]) as db:
        await SupportSettingsService.import_legacy_file(db)
        assert await get_setting_value(db, 'SUPPORT_SYSTEM_MODE') == 'tickets'
        assert SupportSettingsService.get_system_mode() == 'both'
        assert SupportSettingsService.is_tickets_enabled() is True
        assert SupportSettingsService.is_contact_enabled() is True
