from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.handlers import menu as menu_handler
from app.keyboards.inline import get_info_menu_keyboard


def _callbacks(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data]


def _buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def test_rules_button_shown_by_default():
    markup = get_info_menu_keyboard()
    assert 'menu_rules' in _callbacks(markup)


def test_rules_button_hidden_when_disabled():
    markup = get_info_menu_keyboard(show_rules=False)
    assert 'menu_rules' not in _callbacks(markup)


def test_custom_page_buttons_added():
    markup = get_info_menu_keyboard(custom_pages=[(5, '📄 О сервисе'), (7, 'Гайд')])
    callbacks = _callbacks(markup)
    assert 'info_page:5:1' in callbacks
    assert 'info_page:7:1' in callbacks


def test_no_custom_buttons_without_pages():
    markup = get_info_menu_keyboard()
    assert not [cb for cb in _callbacks(markup) if cb.startswith('info_page:')]


def test_legal_documents_are_direct_url_buttons():
    markup = get_info_menu_keyboard(
        privacy_policy_url='https://example.com/privacy',
        public_offer_url='https://example.com/offer',
    )
    buttons = _buttons(markup)

    privacy = next(button for button in buttons if button.url == 'https://example.com/privacy')
    offer = next(button for button in buttons if button.url == 'https://example.com/offer')

    assert privacy.callback_data is None
    assert privacy.icon_custom_emoji_id == '5251203410396458957'
    assert not privacy.text.startswith('🛡')
    assert offer.callback_data is None
    assert offer.icon_custom_emoji_id == '5334544901428229844'
    assert not offer.text.startswith('📄')
    assert 'menu_privacy_policy' not in _callbacks(markup)
    assert 'menu_public_offer' not in _callbacks(markup)


@pytest.mark.asyncio
async def test_rules_back_button_returns_to_info(monkeypatch):
    callback = SimpleNamespace(
        data='menu_rules',
        message=SimpleNamespace(edit_text=AsyncMock()),
        answer=AsyncMock(),
    )
    user = SimpleNamespace(language='ru')

    monkeypatch.setattr(menu_handler.settings, 'SERVICE_RULES_DISPLAY_MODE', 'both')
    monkeypatch.setattr(
        'app.database.crud.rules.get_current_rules_content',
        AsyncMock(return_value='Правила'),
    )

    await menu_handler.show_service_rules(callback, user, AsyncMock())

    markup = callback.message.edit_text.await_args.kwargs['reply_markup']
    assert _callbacks(markup)[-1] == 'menu_info'
