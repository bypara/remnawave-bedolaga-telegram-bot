import inspect
import json
from pathlib import Path

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.handlers import tickets
from app.utils.custom_emoji_buttons import apply_custom_emoji_icons


BRAND_LOCALES = Path(__file__).parents[1] / 'app' / 'localization' / 'brand_locales'


def test_ticket_lists_and_details_use_requested_copy_in_both_languages():
    expected_ids = {
        'MY_TICKETS_TITLE': ('5260233433107407649',),
        'CLOSED_TICKETS_TITLE': ('5210952531676504517',),
        'TICKET_DETAIL_HEADER': (
            '5258216851472654189',
            '5257965174979042426',
            '5258474669769497337',
            '5258096772776991776',
        ),
        'TICKET_MESSAGES_HEADER': ('5257965174979042426',),
        'TICKET_MESSAGE_USER': ('5316727448644103237',),
        'TICKET_MESSAGE_SUPPORT': ('5258486128742244085',),
    }

    for language in ('ru', 'en'):
        locale = json.loads((BRAND_LOCALES / f'{language}.json').read_text(encoding='utf-8'))
        for key, emoji_ids in expected_ids.items():
            for emoji_id in emoji_ids:
                assert f'emoji-id="{emoji_id}"' in locale[key]

        assert '{ticket_id}' in locale['TICKET_DETAIL_HEADER']
        assert '{title}' in locale['TICKET_DETAIL_HEADER']
        assert '{status}' in locale['TICKET_DETAIL_HEADER']
        assert '{created}' in locale['TICKET_DETAIL_HEADER']
        assert '{count}' in locale['TICKET_MESSAGES_HEADER']
        assert '{date}' in locale['TICKET_MESSAGE_USER']
        assert '{date}' in locale['TICKET_MESSAGE_SUPPORT']


def test_open_and_closed_ticket_buttons_use_requested_icons():
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='Открытые тикеты', callback_data='my_tickets')],
            [InlineKeyboardButton(text='Закрытые тикеты', callback_data='my_tickets_closed')],
        ]
    )

    open_button, closed_button = (row[0] for row in apply_custom_emoji_icons(markup).inline_keyboard)

    assert open_button.icon_custom_emoji_id == '5424818078833715060'
    assert closed_button.icon_custom_emoji_id == '5210952531676504517'


def test_ticket_detail_does_not_render_status_emoji_and_uses_html():
    source = inspect.getsource(tickets.view_ticket)

    assert 'ticket.status_emoji' not in source
    assert "parse_mode='HTML'" in source
    assert "TICKET_MESSAGE_USER" in source
    assert "TICKET_MESSAGE_SUPPORT" in source
