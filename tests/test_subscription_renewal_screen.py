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


def test_tariff_list_packs_short_plans_two_per_row():
    tariffs = [
        SimpleNamespace(
            id=index,
            name=name,
            is_daily=False,
            period_prices={'14': price},
        )
        for index, (name, price) in enumerate((('Минимум', 50000), ('Стандарт', 90000)), start=1)
    ]

    keyboard = tariff_purchase.get_tariffs_keyboard(tariffs, 'ru')

    assert len(keyboard.inline_keyboard[0]) == 2
    assert keyboard.inline_keyboard[0][0].text == 'Минимум · от 500₽'
    assert keyboard.inline_keyboard[0][1].text == 'Стандарт · от 900₽'


def test_tariff_info_uses_localized_copy_and_custom_emoji():
    tariff = SimpleNamespace(
        name='Стандартный',
        description='Базовый тарифный план',
        traffic_limit_gb=100,
        device_limit=1,
    )

    rendered = tariff_purchase.format_tariff_info_for_user(tariff, 'ru')

    assert '5260730055880876557' in rendered
    assert '• Трафик: 100 ГБ' in rendered
    assert '5257965174979042426' in rendered
    assert 'Выберите период подписки' not in rendered


@pytest.mark.asyncio
async def test_tariff_period_selection_does_not_require_subscription(monkeypatch):
    tariff = SimpleNamespace(
        id=7,
        name='Стандартный',
        is_active=True,
        period_prices={'14': 50000},
        traffic_limit_gb=100,
        device_limit=1,
        allowed_squads=[],
    )
    user = SimpleNamespace(id=3, language='ru', balance_kopeks=100000)
    callback = SimpleNamespace(
        data='tariff_period:7:14',
        message=SimpleNamespace(edit_text=AsyncMock()),
        answer=AsyncMock(),
    )
    state = AsyncMock()

    monkeypatch.setattr(type(tariff_purchase.settings), 'is_multi_tariff_enabled', lambda self: False)
    monkeypatch.setattr(tariff_purchase, 'get_tariff_by_id', AsyncMock(return_value=tariff))
    monkeypatch.setattr(tariff_purchase, '_get_user_period_discount', lambda _user, _period: (0, 0, 0))
    monkeypatch.setattr(
        tariff_purchase,
        'get_tariff_confirm_keyboard',
        MagicMock(return_value=InlineKeyboardMarkup(inline_keyboard=[])),
    )

    await tariff_purchase.select_tariff_period(callback, user, AsyncMock(), state)

    rendered = callback.message.edit_text.await_args.args[0]
    assert '5258501105293205250' in rendered
    assert 'Трафик: 0 / 100 ГБ' in rendered
    assert 'К оплате: 500 ₽' in rendered
    state.update_data.assert_awaited()
