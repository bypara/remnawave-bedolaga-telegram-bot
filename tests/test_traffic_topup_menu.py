from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.keyboards.inline import get_main_menu_keyboard, get_subscription_keyboard
from app.services.menu_layout import MenuContext
from app.services.menu_layout.service import MenuLayoutService


def _callbacks(markup) -> list[str]:
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


def _subscription(can_topup: bool):
    tariff = SimpleNamespace(
        can_topup_traffic=lambda: can_topup,
        is_daily=False,
        is_free=False,
    )
    return SimpleNamespace(
        id=1,
        subscription_url=None,
        subscription_crypto_link=None,
        is_trial=False,
        traffic_limit_gb=100,
        tariff_id=1,
        tariff=tariff,
        actual_status='active',
        status='active',
    )


def test_main_menu_never_duplicates_traffic_topup():
    markup = get_main_menu_keyboard(
        language='ru',
        has_active_subscription=True,
        subscription_is_active=True,
        subscription=_subscription(can_topup=True),
    )

    assert 'buy_traffic' not in _callbacks(markup)


def test_subscription_menu_respects_tariff_traffic_topup_setting(monkeypatch):
    monkeypatch.setattr(settings, 'SALES_MODE', 'tariffs')

    denied = get_subscription_keyboard('ru', True, False, _subscription(can_topup=False))
    allowed = get_subscription_keyboard('ru', True, False, _subscription(can_topup=True))

    assert 'buy_traffic' not in _callbacks(denied)
    assert 'buy_traffic' in _callbacks(allowed)


@pytest.mark.asyncio
async def test_saved_custom_main_menu_also_hides_traffic_topup(monkeypatch):
    config = {
        'rows': [{'id': 'legacy_traffic', 'buttons': ['buy_traffic'], 'max_per_row': 1}],
        'buttons': {
            'buy_traffic': {
                'type': 'builtin',
                'builtin_id': 'buy_traffic',
                'text': {'ru': '📈 Докупить трафик'},
                'action': 'buy_traffic',
                'enabled': True,
                'visibility': 'subscribers',
            }
        },
    }
    monkeypatch.setattr(MenuLayoutService, 'get_config', AsyncMock(return_value=config))
    context = MenuContext(has_active_subscription=True)

    markup = await MenuLayoutService.build_keyboard(None, context)
    preview = await MenuLayoutService.preview_keyboard(None, context)

    assert markup.inline_keyboard == []
    assert preview == []
