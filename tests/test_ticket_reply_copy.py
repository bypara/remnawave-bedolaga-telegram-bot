import inspect
import json
from pathlib import Path

from app.handlers import tickets
from app.handlers.admin import tickets as admin_tickets
from app.keyboards.inline import (
    TICKET_CLOSE_CUSTOM_EMOJI_ID,
    TICKET_REPLY_CUSTOM_EMOJI_ID,
    get_admin_ticket_view_keyboard,
    get_ticket_notification_keyboard,
    get_ticket_view_keyboard,
)


BRAND_LOCALES = Path(__file__).parents[1] / 'app' / 'localization' / 'brand_locales'


def _button_by_callback(keyboard, callback_data):
    return next(
        button
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data == callback_data
    )


def test_ticket_reply_copy_is_localized_with_requested_custom_emoji():
    for language in ('ru', 'en'):
        locale = json.loads((BRAND_LOCALES / f'{language}.json').read_text(encoding='utf-8'))

        assert 'emoji-id="5260341314095947411"' in locale['TICKET_REPLY_SENT']
        assert locale['ADMIN_TICKET_REPLY_SENT'] == locale['TICKET_REPLY_SENT']
        assert 'emoji-id="5253742260054409879"' in locale['TICKET_REPLY_NOTIFICATION']
        assert '{ticket_id}' in locale['TICKET_REPLY_NOTIFICATION']
        assert '{reply_preview}' in locale['TICKET_REPLY_NOTIFICATION']
        assert 'button below' not in locale['TICKET_REPLY_NOTIFICATION'].lower()
        assert 'кнопку ниже' not in locale['TICKET_REPLY_NOTIFICATION'].lower()


def test_ticket_action_buttons_use_requested_icons_everywhere():
    keyboards = (
        get_ticket_view_keyboard(7, language='ru'),
        get_admin_ticket_view_keyboard(7, language='ru'),
        get_ticket_notification_keyboard(7, language='ru'),
    )

    for keyboard in keyboards:
        reply = _button_by_callback(keyboard, 'reply_ticket_7' if keyboard is keyboards[0] else 'admin_reply_ticket_7')
        close = _button_by_callback(keyboard, 'close_ticket_7' if keyboard is keyboards[0] else 'admin_close_ticket_7')

        assert reply.text == 'Ответить'
        assert reply.icon_custom_emoji_id == TICKET_REPLY_CUSTOM_EMOJI_ID == '5253742260054409879'
        assert close.text == 'Закрыть тикет'
        assert close.icon_custom_emoji_id == TICKET_CLOSE_CUSTOM_EMOJI_ID == '5240241223632954241'


def test_reply_handlers_render_custom_emoji_as_html_and_keep_full_notification_text():
    user_source = inspect.getsource(tickets.handle_ticket_reply)
    admin_source = inspect.getsource(admin_tickets.handle_admin_ticket_reply)
    notification_source = inspect.getsource(admin_tickets.notify_user_about_ticket_reply)

    assert "parse_mode='HTML'" in user_source
    assert "parse_mode='HTML'" in admin_source
    assert "reply_preview=html.escape(reply_text)" in notification_source
    assert "reply_text[:100]" not in notification_source
