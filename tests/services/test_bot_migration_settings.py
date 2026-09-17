from unittest.mock import AsyncMock

import pytest

from app.bot_migration_config import validate_migration_value
from app.config import Settings, settings
from app.services.system_settings_service import bot_configuration_service as service


def test_defaults_and_admin_category():
    config = Settings(BOT_TOKEN='test-token', _env_file=None)
    assert config.BOT_MIGRATION_ENABLED is False
    assert config.BOT_MIGRATION_URL == ''
    for key in ('BOT_MIGRATION_ENABLED', 'BOT_MIGRATION_URL', 'BOT_MIGRATION_MESSAGE', 'BOT_MIGRATION_BUTTON_TEXT'):
        assert service.get_definition(key).category_key == 'BOT_MIGRATION'
        assert not service.is_secret_key(key)


@pytest.mark.parametrize(
    'url',
    [
        'https://t.me/new_service_bot',
        'https://t.me/new_service_bot?start=campaign_50',
    ],
)
def test_valid_links(url):
    assert service.parse_user_value('BOT_MIGRATION_URL', url) == url
    assert service.deserialize_value('BOT_MIGRATION_URL', url) == url
    assert Settings(BOT_TOKEN='test-token', BOT_MIGRATION_ENABLED=True, BOT_MIGRATION_URL=url, _env_file=None)


@pytest.mark.parametrize(
    'url',
    [
        'javascript:alert(1)',
        'http://t.me/new_service_bot',
        'https://t.me.evil.org/new_service_bot',
        'https://user@t.me/new_service_bot',
        'https://t.me/new_service_bot/extra',
        'https://t.me/new_service_bot?start=',
        'https://t.me/new_service_bot?start=a&start=b',
        'https://t.me/new_service_bot?start=' + 'a' * 65,
        'https://t.me/new_service_bot#fragment',
        'https://t.me/new_service_bot?start=x&other=y',
    ],
)
def test_invalid_links_rejected(url):
    with pytest.raises(ValueError):
        service.parse_user_value('BOT_MIGRATION_URL', url)
    with pytest.raises(ValueError):
        Settings(BOT_TOKEN='test-token', BOT_MIGRATION_URL=url, _env_file=None)


@pytest.mark.parametrize(
    ('key', 'value'),
    [
        ('BOT_MIGRATION_MESSAGE', ''),
        ('BOT_MIGRATION_MESSAGE', 'x' * 3501),
        ('BOT_MIGRATION_BUTTON_TEXT', ' '),
        ('BOT_MIGRATION_BUTTON_TEXT', 'x' * 65),
        ('BOT_MIGRATION_BUTTON_TEXT', '🎁' * 33),
    ],
)
def test_text_limits(key, value):
    with pytest.raises(ValueError):
        validate_migration_value(key, value)


def test_environment_cannot_enable_without_target():
    with pytest.raises(ValueError, match='BOT_MIGRATION_URL'):
        Settings(BOT_TOKEN='test-token', BOT_MIGRATION_ENABLED=True, BOT_MIGRATION_URL='', _env_file=None)


async def test_live_enable_requires_url_before_database_write(monkeypatch):
    monkeypatch.setattr(settings, 'BOT_MIGRATION_URL', '')
    db = AsyncMock()
    upsert = AsyncMock()
    monkeypatch.setattr('app.services.system_settings_service.upsert_system_setting', upsert)
    with pytest.raises(ValueError, match='ссылку'):
        await service.set_value(db, 'BOT_MIGRATION_ENABLED', True)
    upsert.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_active_target_cannot_be_removed_or_reset(monkeypatch):
    monkeypatch.setattr(settings, 'BOT_MIGRATION_ENABLED', True)
    monkeypatch.setattr(service, 'get_original_value', classmethod(lambda cls, key: ''))
    db = AsyncMock()
    with pytest.raises(ValueError, match='отключите'):
        await service.set_value(db, 'BOT_MIGRATION_URL', '')
    with pytest.raises(ValueError, match='отключите'):
        await service.reset_value(db, 'BOT_MIGRATION_URL')
    db.commit.assert_not_awaited()


async def test_invalid_api_value_rejected_before_write(monkeypatch):
    upsert = AsyncMock()
    monkeypatch.setattr('app.services.system_settings_service.upsert_system_setting', upsert)
    with pytest.raises(ValueError):
        await service.set_value(AsyncMock(), 'BOT_MIGRATION_URL', 'https://example.com')
    upsert.assert_not_awaited()


async def test_valid_setting_is_committed_and_applied_live(monkeypatch):
    monkeypatch.setattr(settings, 'BOT_MIGRATION_ENABLED', False)
    monkeypatch.setattr(settings, 'BOT_MIGRATION_URL', 'https://t.me/new_service_bot')
    monkeypatch.setattr(service, '_is_env_override', classmethod(lambda cls, key: False))
    monkeypatch.setattr(service, '_overrides_raw', {})
    upsert = AsyncMock()
    monkeypatch.setattr('app.services.system_settings_service.upsert_system_setting', upsert)
    db = AsyncMock()
    await service.set_value(db, 'BOT_MIGRATION_ENABLED', True)
    upsert.assert_awaited_once_with(db, 'BOT_MIGRATION_ENABLED', 'true')
    db.commit.assert_awaited_once()
    assert settings.BOT_MIGRATION_ENABLED is True
    await service.set_value(db, 'BOT_MIGRATION_ENABLED', False)
    assert settings.BOT_MIGRATION_ENABLED is False


async def test_cabinet_enable_without_url_returns_actionable_400(monkeypatch):
    from fastapi import HTTPException

    from app.cabinet.routes.admin_settings import SettingUpdateRequest, update_setting

    monkeypatch.setattr(settings, 'BOT_MIGRATION_URL', '')
    monkeypatch.setattr(service, 'is_env_locked', classmethod(lambda cls, key: False))
    with pytest.raises(HTTPException) as caught:
        await update_setting('BOT_MIGRATION_ENABLED', SettingUpdateRequest(value=True), admin=None, db=AsyncMock())
    assert caught.value.status_code == 400
    assert 'ссылку' in caught.value.detail


async def test_cabinet_reset_active_target_returns_400(monkeypatch):
    from fastapi import HTTPException

    from app.cabinet.routes.admin_settings import reset_setting

    monkeypatch.setattr(settings, 'BOT_MIGRATION_ENABLED', True)
    monkeypatch.setattr(service, 'get_original_value', classmethod(lambda cls, key: ''))
    monkeypatch.setattr(service, 'is_env_locked', classmethod(lambda cls, key: False))
    with pytest.raises(HTTPException) as caught:
        await reset_setting('BOT_MIGRATION_URL', admin=None, db=AsyncMock())
    assert caught.value.status_code == 400


@pytest.mark.parametrize('amount', [0, 1, 75.50, 100000])
def test_bonus_currency_exact(amount):
    from app.bot_migration_config import migration_bonus_kopeks, render_migration_text

    kopeks = migration_bonus_kopeks(amount)
    assert kopeks == int(amount * 100)
    text = render_migration_text('Бонус {bonus} ₽. Другие {скобки} остаются.', kopeks)
    assert '{bonus}' not in text
    assert '{скобки}' in text


@pytest.mark.parametrize('amount', [-1, 100000.01, 0.001, 'nan', 'inf', 'invalid'])
def test_invalid_bonus_amount_rejected(amount):
    with pytest.raises(ValueError):
        service.parse_user_value('BOT_MIGRATION_BONUS_AMOUNT_RUBLES', str(amount))
    with pytest.raises(ValueError):
        Settings(BOT_TOKEN='test-token', BOT_MIGRATION_BONUS_AMOUNT_RUBLES=amount, _env_file=None)


async def test_bonus_requires_positive_amount_and_cannot_be_zeroed_while_active(monkeypatch):
    monkeypatch.setattr(settings, 'BOT_MIGRATION_URL', 'https://t.me/new_service_bot')
    monkeypatch.setattr(settings, 'BOT_MIGRATION_BONUS_AMOUNT_RUBLES', 0)
    with pytest.raises(ValueError, match='сумму'):
        await service.set_value(AsyncMock(), 'BOT_MIGRATION_BONUS_ENABLED', True)
    monkeypatch.setattr(settings, 'BOT_MIGRATION_BONUS_ENABLED', True)
    with pytest.raises(ValueError, match='отключите'):
        await service.set_value(AsyncMock(), 'BOT_MIGRATION_BONUS_AMOUNT_RUBLES', 0)


def test_bonus_and_fallback_settings_are_visible_and_not_secrets():
    for key in (
        'BOT_MIGRATION_BONUS_ENABLED',
        'BOT_MIGRATION_BONUS_AMOUNT_RUBLES',
        'BOT_MIGRATION_BONUS_SUCCESS_MESSAGE',
        'BOT_MIGRATION_NO_BONUS_MESSAGE',
        'BOT_MIGRATION_NO_BONUS_BUTTON_TEXT',
    ):
        assert service.get_definition(key).category_key == 'BOT_MIGRATION'
        assert not service.is_secret_key(key)


def test_placeholder_expansion_cannot_overflow_button_limit():
    with pytest.raises(ValueError):
        validate_migration_value('BOT_MIGRATION_BUTTON_TEXT', '{bonus}' * 9)
