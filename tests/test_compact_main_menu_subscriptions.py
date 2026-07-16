from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.handlers import menu
from app.localization.texts import get_texts


def _subscription(*, tariff_name: str, url: str, days: int, subscription_id: int):
    return SimpleNamespace(
        id=subscription_id,
        actual_status='active',
        end_date=datetime.now(UTC) + timedelta(days=days, hours=1),
        tariff_id=subscription_id,
        tariff=SimpleNamespace(name=tariff_name),
        subscription_url=url,
        subscription_crypto_link=None,
    )


async def test_compact_main_menu_subscription_is_copyable(monkeypatch):
    subscription = _subscription(
        tariff_name='Стандартный',
        url='https://sub.example/test?key=1&device=2',
        days=13,
        subscription_id=1,
    )
    user = SimpleNamespace(id=1, subscription=subscription)

    monkeypatch.setattr(type(menu.settings), 'is_multi_tariff_enabled', lambda self: False)
    monkeypatch.setattr(type(menu.settings), 'should_hide_subscription_link', lambda self: False)

    result = await menu._build_compact_main_menu_subscriptions(user, get_texts('ru'), AsyncMock())

    assert 'emoji-id="5255850874248399164"' in result
    assert '<b>Стандартный</b>' in result
    assert 'emoji-id="5258105663359294787"' in result
    assert f'<tg-time unix="{int(subscription.end_date.timestamp())}" format="d">' in result
    assert 'осталось' not in result
    assert 'emoji-id="5260730055880876557"' in result
    assert '<code>https://sub.example/test?key=1&amp;device=2</code>' in result


async def test_compact_main_menu_supports_multiple_tariffs(monkeypatch):
    subscriptions = [
        _subscription(tariff_name='Стандартный', url='https://sub.example/one', days=13, subscription_id=1),
        _subscription(tariff_name='Премиум', url='https://sub.example/two', days=30, subscription_id=2),
    ]
    user = SimpleNamespace(id=1, subscription=subscriptions[0])

    monkeypatch.setattr(type(menu.settings), 'is_multi_tariff_enabled', lambda self: True)
    monkeypatch.setattr(type(menu.settings), 'should_hide_subscription_link', lambda self: False)

    async def fake_get_all(db, user_id):
        return subscriptions

    monkeypatch.setattr(menu, 'get_all_subscriptions_by_user_id', fake_get_all)

    result = await menu._build_compact_main_menu_subscriptions(user, get_texts('ru'), AsyncMock())

    assert result.count('emoji-id="5255850874248399164"') == 2
    assert result.count('<tg-time unix=') == 2
    assert result.count('<code>https://sub.example/') == 2
    assert 'Стандартный' in result
    assert 'Премиум' in result
