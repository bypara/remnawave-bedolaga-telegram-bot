import inspect
import json
from pathlib import Path

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.handlers import tickets
from app.utils.custom_emoji_buttons import apply_custom_emoji_icons


BRAND_LOCALES = Path(__file__).parents[1] / 'app' / 'localization' / 'brand_locales'


def test_ticket_created_message_uses_requested_copy_in_both_languages():
    expected_emoji_ids = (
        '5206607081334906820',
        '5257965174979042426',
        '5323761960829862762',
    )

    for language in ('ru', 'en'):
        locale = json.loads((BRAND_LOCALES / f'{language}.json').read_text(encoding='utf-8'))
        value = locale['TICKET_CREATED_MESSAGE']

        for emoji_id in expected_emoji_ids:
            assert f'emoji-id="{emoji_id}"' in value
        assert '{ticket_id}' in value
        assert '{title}' in value
        assert '{status}' in value


def test_ticket_created_message_has_plain_status_and_custom_view_button():
    source = inspect.getsource(tickets.handle_ticket_message_input)

    assert 'ticket.status_emoji' not in source
    assert 'format_local_datetime(ticket.created_at' not in source
    assert 'Вложение: фото' not in source
    assert source.count('icon_custom_emoji_id=VIEW_TICKET_CUSTOM_EMOJI_ID') == 1
    assert tickets.VIEW_TICKET_CUSTOM_EMOJI_ID == '5253959125838090076'


def test_view_ticket_button_does_not_keep_duplicate_unicode_emoji():
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text='👁️ Посмотреть тикет',
                    callback_data='view_ticket_1',
                    icon_custom_emoji_id=tickets.VIEW_TICKET_CUSTOM_EMOJI_ID,
                )
            ]
        ]
    )

    button = apply_custom_emoji_icons(markup).inline_keyboard[0][0]

    assert button.text == 'Посмотреть тикет'
    assert button.icon_custom_emoji_id == '5253959125838090076'
