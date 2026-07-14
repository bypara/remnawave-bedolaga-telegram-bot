from unittest.mock import AsyncMock

import pytest

from app.services.menu_layout import MenuContext
from app.services.menu_layout.service import MenuLayoutService


@pytest.mark.asyncio
async def test_saved_combined_purchase_row_is_split_and_reordered(monkeypatch):
    config = {
        'rows': [
            {
                'id': 'legacy_trial_buy_row',
                'buttons': ['trial', 'buy_subscription'],
                'max_per_row': 2,
            }
        ],
        'buttons': {
            'trial': {
                'type': 'builtin',
                'text': {'ru': '🧪 Тестовая подписка'},
                'action': 'menu_trial',
                'enabled': True,
            },
            'buy_subscription': {
                'type': 'builtin',
                'text': {'ru': '💎 Купить подписку'},
                'action': 'menu_buy',
                'enabled': True,
            },
        },
    }
    monkeypatch.setattr(MenuLayoutService, 'get_config', AsyncMock(return_value=config))
    context = MenuContext(language='ru')

    markup = await MenuLayoutService.build_keyboard(None, context)
    preview = await MenuLayoutService.preview_keyboard(None, context)

    assert [[button.callback_data for button in row] for row in markup.inline_keyboard] == [
        ['menu_buy'],
        ['menu_trial'],
    ]
    assert [[button['action'] for button in row['buttons']] for row in preview] == [
        ['menu_buy'],
        ['menu_trial'],
    ]
