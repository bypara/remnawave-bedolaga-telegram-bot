from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.admin_notification_service import AdminNotificationService, NotificationCategory
from app.utils.purchase_source import get_purchase_source, get_subscription_purchase_description


def _purchase(source, **overrides):
    values = {
        'id': 18,
        'source': source,
        'is_gift': True,
        'contact_type': 'telegram',
        'contact_value': '@sender',
        'buyer': SimpleNamespace(username='sender'),
        'user': None,
        'landing': None,
        'landing_id': None,
        'gift_recipient_value': None,
        'gift_recipient_type': None,
        'gift_message': None,
        'payment_method': 'balance',
        'payment_id': None,
        'period_days': 30,
        'amount_kopeks': 22900,
    }
    return SimpleNamespace(**(values | overrides))


def _admin_service():
    service = AdminNotificationService(SimpleNamespace())
    service.enabled = True
    service.chat_id = -100123456
    service._send_message = AsyncMock(return_value=True)
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('source', 'title'),
    [('bot', 'ПОДАРОК ИЗ БОТА'), ('cabinet', 'ПОДАРОК ИЗ КАБИНЕТА'), ('landing', 'ПОДАРОК С ЛЕНДИНГА')],
)
async def test_paid_gift_notification_names_its_real_source(source, title):
    purchase = _purchase(source)
    if source == 'landing':
        purchase.landing = SimpleNamespace(slug='summer')
        purchase.landing_id = 3
    service = _admin_service()

    assert await service.send_guest_purchase_notification(purchase, 'Максимум', is_pending_activation=True)

    text = service._send_message.await_args.args[0]
    assert title in text
    assert '#18' in text
    assert 'оплачен, ожидает активации' in text
    assert '<a href="https://t.me/sender">@sender</a>' in text
    assert ('/buy/summer' in text) is (source == 'landing')
    assert '/buy/—' not in text
    assert service._send_message.await_args.kwargs['category'] == NotificationCategory.PURCHASES


@pytest.mark.asyncio
@pytest.mark.parametrize('source', ['bot', 'cabinet', 'landing'])
async def test_gift_activation_names_actual_recipient_and_is_not_a_second_sale(source):
    purchase = _purchase(source, user=SimpleNamespace(username='actual_recipient'), gift_recipient_value='@typed_contact')
    service = _admin_service()

    assert await service.send_guest_purchase_notification(purchase, 'Максимум', is_activation=True)

    text = service._send_message.await_args.args[0]
    assert 'ПОДАРОК АКТИВИРОВАН' in text
    assert 'Источник:' in text
    assert 'Получатель: <a href="https://t.me/actual_recipient">@actual_recipient</a>' in text
    assert 'по коду активации' not in text
    assert '@typed_contact' not in text
    assert 'оплачен, ожидает активации' not in text


@pytest.mark.asyncio
@pytest.mark.parametrize('source', [None, '', 'unknown', 'landing'])
async def test_missing_landing_never_generates_a_fake_page(source):
    service = _admin_service()

    assert await service.send_guest_purchase_notification(_purchase(source, buyer=None), 'Максимум')

    text = service._send_message.await_args.args[0]
    assert '/buy/' not in text
    if source != 'landing':
        assert 'С ЛЕНДИНГА' not in text
        assert 'Источник: не указан' in text


@pytest.mark.parametrize(
    ('source', 'expected'),
    [
        ('bot', 'Покупка подписки через бота'),
        ('cabinet', 'Покупка подписки через личный кабинет'),
        ('landing', 'Покупка подписки через лендинг'),
        (None, 'Покупка подписки'),
    ],
)
def test_transaction_description_uses_actual_purchase_source(source, expected):
    assert get_subscription_purchase_description(_purchase(source), 'Максимум') == f'{expected} (Максимум, 30 дн.)'


def test_legacy_purchase_can_be_recognized_by_real_landing_id():
    assert get_purchase_source(_purchase(None, landing_id=3)) == 'landing'
