from app.config import settings
from app.keyboards.inline import get_support_keyboard
from app.services.support_settings_service import SupportSettingsService
from app.services.system_settings_service import bot_configuration_service


def _set_cached_support_data(monkeypatch, data: dict) -> None:
    monkeypatch.setattr(SupportSettingsService, '_loaded', True)
    monkeypatch.setattr(SupportSettingsService, '_data', data)


def test_env_support_mode_wins_over_stale_legacy_json(monkeypatch):
    _set_cached_support_data(monkeypatch, {'system_mode': 'tickets'})
    monkeypatch.setattr(settings, 'SUPPORT_SYSTEM_MODE', 'both')
    monkeypatch.setattr(bot_configuration_service, 'is_env_overridden', lambda key: key == 'SUPPORT_SYSTEM_MODE')
    monkeypatch.setattr(bot_configuration_service, 'has_override', lambda key: False)

    assert SupportSettingsService.get_system_mode() == 'both'
    assert SupportSettingsService.is_tickets_enabled() is True
    assert SupportSettingsService.is_contact_enabled() is True


def test_both_env_mode_renders_tickets_and_direct_contact(monkeypatch):
    _set_cached_support_data(monkeypatch, {'system_mode': 'tickets'})
    monkeypatch.setattr(settings, 'SUPPORT_SYSTEM_MODE', 'both')
    monkeypatch.setattr(settings, 'SUPPORT_USERNAME', '@bypara')
    monkeypatch.setattr(bot_configuration_service, 'is_env_overridden', lambda key: key == 'SUPPORT_SYSTEM_MODE')
    monkeypatch.setattr(bot_configuration_service, 'has_override', lambda key: False)

    keyboard = get_support_keyboard('ru')
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.callback_data == 'create_ticket' for button in buttons)
    assert any(button.callback_data == 'my_tickets' for button in buttons)
    assert any(button.url == 'https://t.me/bypara' for button in buttons)


def test_global_support_override_wins_over_stale_legacy_json(monkeypatch):
    _set_cached_support_data(monkeypatch, {'system_mode': 'contact'})
    monkeypatch.setattr(settings, 'SUPPORT_SYSTEM_MODE', 'tickets')
    monkeypatch.setattr(bot_configuration_service, 'is_env_overridden', lambda key: False)
    monkeypatch.setattr(bot_configuration_service, 'has_override', lambda key: key == 'SUPPORT_SYSTEM_MODE')

    assert SupportSettingsService.get_system_mode() == 'tickets'


def test_legacy_support_mode_remains_available_without_global_override(monkeypatch):
    _set_cached_support_data(monkeypatch, {'system_mode': 'contact'})
    monkeypatch.setattr(settings, 'SUPPORT_SYSTEM_MODE', 'both')
    monkeypatch.setattr(bot_configuration_service, 'is_env_overridden', lambda key: False)
    monkeypatch.setattr(bot_configuration_service, 'has_override', lambda key: False)

    assert SupportSettingsService.get_system_mode() == 'contact'
