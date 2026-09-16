from app.config import settings
from app.keyboards.inline import get_support_keyboard
from app.services.support_settings_service import SupportSettingsService


def test_live_support_mode_is_shared_with_cabinet(monkeypatch):
    for mode, tickets, contact in (
        ('both', True, True),
        ('contact', False, True),
        ('tickets', True, False),
    ):
        monkeypatch.setattr(settings, 'SUPPORT_SYSTEM_MODE', mode)
        assert SupportSettingsService.get_system_mode() == mode
        assert SupportSettingsService.is_tickets_enabled() is tickets
        assert settings.is_support_tickets_enabled() is tickets
        assert SupportSettingsService.is_contact_enabled() is contact


def test_both_mode_renders_tickets_and_direct_contact(monkeypatch):
    monkeypatch.setattr(settings, 'SUPPORT_SYSTEM_MODE', 'both')
    monkeypatch.setattr(settings, 'SUPPORT_USERNAME', '@bypara')
    monkeypatch.setattr(settings, 'SUPPORT_MENU_ENABLED', True)
    keyboard = get_support_keyboard('ru')
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.callback_data == 'create_ticket' for button in buttons)
    assert any(button.callback_data == 'my_tickets' for button in buttons)
    assert any(button.url == 'https://t.me/bypara' for button in buttons)
