from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.database.crud import landing, tariff
from app.services import guest_purchase_service
from app.services.payment.common import try_fulfill_guest_purchase


@pytest.mark.asyncio
@pytest.mark.parametrize('recipient_type', [None, 'email'])
async def test_gift_payment_is_reported_before_claim_and_only_once(monkeypatch, recipient_type):
    purchase = SimpleNamespace(
        id=18,
        status='pending',
        is_gift=True,
        gift_recipient_type=recipient_type,
        buyer=SimpleNamespace(id=1),
        tariff=SimpleNamespace(name='Максимум'),
        tariff_id=8,
        period_days=30,
        amount_kopeks=22900,
        paid_at=None,
    )
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: purchase))),
        commit=AsyncMock(),
        refresh=AsyncMock(),
        rollback=AsyncMock(),
    )

    async def mark_paid(*_args, **kwargs):
        purchase.status = 'paid'
        purchase.paid_at = kwargs['paid_at']

    update_status = AsyncMock(side_effect=mark_paid)
    notify_paid = AsyncMock()
    notify_claim = AsyncMock()
    monkeypatch.setattr(landing, 'update_purchase_status', update_status)
    monkeypatch.setattr(tariff, 'get_tariff_by_id', AsyncMock(return_value=purchase.tariff))
    monkeypatch.setattr(guest_purchase_service, 'notify_paid_gift_purchase', notify_paid)
    monkeypatch.setattr(guest_purchase_service, 'notify_gift_claim_available', notify_claim)
    monkeypatch.setattr(guest_purchase_service, '_create_nalogo_receipt_for_purchase', AsyncMock())
    fulfill = AsyncMock()
    monkeypatch.setattr(guest_purchase_service, 'fulfill_purchase', fulfill)

    kwargs = {
        'metadata': {'purpose': 'guest_purchase', 'purchase_token': 'test-token'},
        'payment_amount_kopeks': 22900,
        'provider_payment_id': 'test-payment',
        'provider_name': 'anore',
    }
    assert await try_fulfill_guest_purchase(db, **kwargs) is True
    paid_at = purchase.paid_at
    assert paid_at <= datetime.now(UTC)
    assert await try_fulfill_guest_purchase(db, **kwargs) is True

    assert purchase.status == 'paid'  # Waits for its recipient; no subscription yet.
    assert purchase.paid_at == paid_at
    update_status.assert_awaited_once()
    notify_paid.assert_awaited_once_with(purchase, 'Максимум')
    notify_claim.assert_awaited_once()
    fulfill.assert_not_awaited()
    db.rollback.assert_not_awaited()
