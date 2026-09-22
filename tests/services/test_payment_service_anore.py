"""Creation, verification and idempotency scenarios for Anore payments."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

import app.database.crud.anore as anore_crud
import app.services.payment.anore as anore_mixin
from app.config import settings
from app.services import payment_service as payment_service_module
from app.services.anore_service import AnoreAPIError
from app.services.payment_service import PaymentService


class DummySession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def flush(self) -> None:
        return None


class FakePayment:
    def __init__(self, *, is_test: bool = False) -> None:
        self.id = 11
        self.user_id = 77
        self.order_id = 'an123456_abcdef1234'
        self.anore_payment_id = None
        self.amount_kopeks = 125000
        self.currency = 'RUB'
        self.status = 'pending'
        self.is_paid = False
        self.is_test = is_test
        self.payment_url = None
        self.payment_method = None
        self.callback_payload = None
        self.processed_events: list[str] = []
        self.metadata_json: dict[str, Any] = {}
        self.paid_at = None
        self.expires_at = None
        self.updated_at = None
        self.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        self.transaction_id = None


class StubAnoreService:
    def __init__(self, *, is_test: bool = False) -> None:
        self.is_test_key = is_test
        self.create_calls: list[dict[str, Any]] = []
        self.status_response: dict[str, Any] = {
            'id': 'provider-id',
            'status': 'paid',
            'paid': True,
            'rubAmount': 1250,
            'currency': 'rub',
            'method': 'sbp',
        }

    async def create_payment(self, **kwargs: Any) -> dict[str, Any]:
        self.create_calls.append(kwargs)
        return {
            'success': True,
            'id': 'provider-id',
            'status': 'new',
            'paymentUrl': 'https://pay.anore.cc/provider-id',
            'expiresIn': 14400,
        }

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        assert payment_id == 'provider-id'
        return self.status_response


@pytest.fixture(autouse=True)
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, 'ANORE_ENABLED', True, raising=False)
    monkeypatch.setattr(settings, 'ANORE_API_KEY', 'an_live_key', raising=False)
    monkeypatch.setattr(settings, 'ANORE_WEBHOOK_SECRET', 'secret', raising=False)
    monkeypatch.setattr(settings, 'ANORE_MIN_AMOUNT_KOPEKS', 10000, raising=False)
    monkeypatch.setattr(settings, 'ANORE_MAX_AMOUNT_KOPEKS', 10000000, raising=False)
    monkeypatch.setattr(settings, 'ANORE_METHODS', 'sbp,crypto,invalid', raising=False)
    monkeypatch.setattr(settings, 'ANORE_CALLBACK_URL', 'https://hooks.example/anore-webhook', raising=False)


def _service() -> PaymentService:
    service = PaymentService.__new__(PaymentService)  # type: ignore[call-arg]
    service.bot = None
    return service


async def _user(_db: Any, _user_id: int) -> Any:
    return type('User', (), {'telegram_id': 123456})()


@pytest.mark.anyio
async def test_create_payment_persists_before_api_and_returns_url(monkeypatch: pytest.MonkeyPatch) -> None:
    payment = FakePayment()
    stub = StubAnoreService()
    create = AsyncMock(return_value=payment)
    lock = AsyncMock(return_value=payment)
    monkeypatch.setattr(anore_mixin, 'anore_service', stub)
    monkeypatch.setattr(anore_crud, 'create_anore_payment', create)
    monkeypatch.setattr(anore_crud, 'get_anore_payment_by_id_for_update', lock)
    monkeypatch.setattr(payment_service_module, 'get_user_by_id', _user)

    result = await _service().create_anore_payment(
        DummySession(),
        user_id=77,
        amount_kopeks=125000,
        description='Пополнение',
        email='buyer@example.com',
        return_url='https://web.example/success',
    )

    assert result is not None
    assert result['payment_url'] == 'https://pay.anore.cc/provider-id'
    assert payment.anore_payment_id == 'provider-id'
    assert payment.status == 'pending'
    assert create.await_args.kwargs['amount_kopeks'] == 125000
    assert stub.create_calls[0]['methods'] == 'sbp,crypto'
    assert stub.create_calls[0]['callback_url'] == 'https://hooks.example/anore-webhook'


@pytest.mark.anyio
async def test_selected_anore_method_is_forwarded_to_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    payment = FakePayment()
    stub = StubAnoreService()
    monkeypatch.setattr(anore_mixin, 'anore_service', stub)
    monkeypatch.setattr(anore_crud, 'create_anore_payment', AsyncMock(return_value=payment))
    monkeypatch.setattr(anore_crud, 'get_anore_payment_by_id_for_update', AsyncMock(return_value=payment))
    monkeypatch.setattr(payment_service_module, 'get_user_by_id', _user)

    result = await _service().create_anore_payment(
        DummySession(),
        user_id=77,
        amount_kopeks=125000,
        payment_method_type='card',
    )

    assert result is not None
    assert stub.create_calls[0]['methods'] == 'yoomoney'


@pytest.mark.anyio
async def test_fast_webhook_success_is_not_overwritten_by_create_response(monkeypatch: pytest.MonkeyPatch) -> None:
    stale = FakePayment()
    finalized = FakePayment()
    finalized.status = 'success'
    finalized.is_paid = True
    stub = StubAnoreService()
    monkeypatch.setattr(anore_mixin, 'anore_service', stub)
    monkeypatch.setattr(anore_crud, 'create_anore_payment', AsyncMock(return_value=stale))
    monkeypatch.setattr(anore_crud, 'get_anore_payment_by_id_for_update', AsyncMock(return_value=finalized))
    monkeypatch.setattr(payment_service_module, 'get_user_by_id', _user)

    await _service().create_anore_payment(DummySession(), user_id=77, amount_kopeks=125000)

    assert finalized.status == 'success'
    assert finalized.is_paid is True


@pytest.mark.anyio
async def test_create_4xx_is_terminal_but_network_like_failure_remains_reconcilable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = FakePayment()
    stub = StubAnoreService()

    async def reject(**_kwargs: Any) -> dict[str, Any]:
        raise AnoreAPIError(422, 'invalid amount')

    stub.create_payment = reject  # type: ignore[method-assign]
    monkeypatch.setattr(anore_mixin, 'anore_service', stub)
    monkeypatch.setattr(anore_crud, 'create_anore_payment', AsyncMock(return_value=payment))
    monkeypatch.setattr(payment_service_module, 'get_user_by_id', _user)

    assert await _service().create_anore_payment(DummySession(), user_id=77, amount_kopeks=125000) is None
    assert payment.status == 'error'


def _patch_callback_crud(monkeypatch: pytest.MonkeyPatch, payment: FakePayment) -> AsyncMock:
    monkeypatch.setattr(anore_crud, 'get_anore_payment_by_order_id', AsyncMock(return_value=payment))
    monkeypatch.setattr(anore_crud, 'get_anore_payment_by_id_for_update', AsyncMock(return_value=payment))

    async def update(*_args: Any, **kwargs: Any) -> FakePayment:
        payment.status = kwargs['status']
        if kwargs.get('is_paid') is not None:
            payment.is_paid = kwargs['is_paid']
        return payment

    update_mock = AsyncMock(side_effect=update)
    monkeypatch.setattr(anore_crud, 'update_anore_payment_status', update_mock)
    return update_mock


def _event() -> dict[str, Any]:
    return {
        'event': 'payment.succeeded',
        'id': 'provider-id',
        'orderId': 'an123456_abcdef1234',
        '_delivery_id': 'delivery-1',
    }


@pytest.mark.anyio
async def test_paid_callback_rechecks_api_and_finalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    payment = FakePayment()
    stub = StubAnoreService()
    _patch_callback_crud(monkeypatch, payment)
    monkeypatch.setattr(anore_mixin, 'anore_service', stub)
    service = _service()
    finalize = AsyncMock(return_value=True)
    monkeypatch.setattr(service, '_finalize_anore_payment', finalize)

    assert await service.process_anore_callback(DummySession(), _event()) is True
    assert payment.status == 'success'
    assert payment.is_paid is True
    assert payment.payment_method == 'sbp'
    assert payment.processed_events == ['delivery-1']
    finalize.assert_awaited_once()


@pytest.mark.anyio
async def test_amount_mismatch_never_finalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    payment = FakePayment()
    stub = StubAnoreService()
    stub.status_response['rubAmount'] = 1249.99
    update = _patch_callback_crud(monkeypatch, payment)
    monkeypatch.setattr(anore_mixin, 'anore_service', stub)
    service = _service()
    finalize = AsyncMock(return_value=True)
    monkeypatch.setattr(service, '_finalize_anore_payment', finalize)

    assert await service.process_anore_callback(DummySession(), _event()) is False
    assert update.await_args.kwargs['status'] == 'amount_mismatch'
    finalize.assert_not_awaited()


@pytest.mark.anyio
async def test_test_key_records_success_without_crediting(monkeypatch: pytest.MonkeyPatch) -> None:
    payment = FakePayment(is_test=True)
    stub = StubAnoreService(is_test=True)
    update = _patch_callback_crud(monkeypatch, payment)
    monkeypatch.setattr(anore_mixin, 'anore_service', stub)
    service = _service()
    finalize = AsyncMock(return_value=True)
    monkeypatch.setattr(service, '_finalize_anore_payment', finalize)

    assert await service.process_anore_callback(DummySession(), _event()) is True
    assert update.await_args.kwargs['status'] == 'success'
    finalize.assert_not_awaited()


@pytest.mark.anyio
async def test_status_api_outage_keeps_provider_id_for_periodic_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    payment = FakePayment()
    stub = StubAnoreService()

    async def unavailable(_payment_id: str) -> dict[str, Any]:
        raise TimeoutError('temporary outage')

    stub.get_payment = unavailable  # type: ignore[method-assign]
    _patch_callback_crud(monkeypatch, payment)
    monkeypatch.setattr(anore_mixin, 'anore_service', stub)
    db = DummySession()

    assert await _service().process_anore_callback(db, _event()) is False
    assert payment.anore_payment_id == 'provider-id'
    assert db.commits == 1
    assert payment.processed_events == []


def test_status_response_may_omit_order_id_but_not_mismatch_it() -> None:
    payment = FakePayment()
    data = StubAnoreService().status_response

    assert anore_mixin.AnorePaymentMixin._anore_payment_matches(payment, data, provider_id='provider-id') is True
    data['orderId'] = 'different-order'
    assert anore_mixin.AnorePaymentMixin._anore_payment_matches(payment, data, provider_id='provider-id') is False
