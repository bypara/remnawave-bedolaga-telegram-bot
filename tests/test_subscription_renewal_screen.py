from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import InlineKeyboardMarkup

from app.handlers.subscription import tariff_purchase
from app.keyboards.inline import get_add_traffic_keyboard_from_tariff


@pytest.mark.asyncio
async def test_tariff_renewal_screen_loads_localization(monkeypatch):
    subscription = SimpleNamespace(
        id=42,
        tariff_id=7,
        traffic_used_gb=4,
        device_limit=1,
    )
    tariff = SimpleNamespace(
        id=7,
        name='Стандартный',
        is_active=True,
        traffic_limit_gb=100,
        device_limit=1,
    )
    user = SimpleNamespace(
        id=3,
        language='ru',
        get_primary_promo_group=lambda: None,
        promo_group=None,
    )
    callback = SimpleNamespace(
        data='subscription_extend',
        message=SimpleNamespace(edit_text=AsyncMock()),
        answer=AsyncMock(),
    )

    monkeypatch.setattr(type(tariff_purchase.settings), 'is_multi_tariff_enabled', lambda self: False)
    monkeypatch.setattr(
        tariff_purchase,
        'get_subscription_by_user_id',
        AsyncMock(return_value=subscription),
    )
    monkeypatch.setattr(
        tariff_purchase,
        'get_tariff_by_id',
        AsyncMock(return_value=tariff),
    )
    monkeypatch.setattr(
        tariff_purchase,
        'get_tariff_extend_keyboard',
        MagicMock(return_value=InlineKeyboardMarkup(inline_keyboard=[])),
    )

    await tariff_purchase.show_tariff_extend(callback, user, AsyncMock())

    rendered = callback.message.edit_text.await_args.args[0]
    assert '5199457120428249992' in rendered
    assert '4 / 100 ГБ' in rendered


def test_add_traffic_button_uses_custom_plus_icon():
    keyboard = get_add_traffic_keyboard_from_tariff(
        language='ru',
        packages={5: 5000},
        subscription_end_date=None,
        discount_percent=0,
    )

    button = keyboard.inline_keyboard[0][0]
    assert button.text.startswith('+5 ГБ трафика')
    assert button.icon_custom_emoji_id == '5274008024585871702'
