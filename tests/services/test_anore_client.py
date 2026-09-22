"""Wire contract and signature checks for the Anore API client."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import pytest

from app.config import settings
from app.services.anore_service import AnoreAPIError, AnoreService


@pytest.fixture(autouse=True)
def anore_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, 'ANORE_API_KEY', 'an_test_key', raising=False)
    monkeypatch.setattr(settings, 'ANORE_WEBHOOK_SECRET', 'cashbox-secret', raising=False)
    monkeypatch.setattr(settings, 'ANORE_SHOP_ID', 42, raising=False)
    monkeypatch.setattr(settings, 'ANORE_BASE_URL', 'https://api.anore.cc/v1', raising=False)


class RecordingService(AnoreService):
    def __init__(self, response: dict[str, Any]) -> None:
        super().__init__()
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({'method': method, 'path': path, **kwargs})
        return self.response


def _created() -> dict[str, Any]:
    return {
        'success': True,
        'id': 'e2dfaa6e-c423-4b5f-95b3-f203933d18f0',
        'orderId': 'an123_test',
        'status': 'new',
        'paymentUrl': 'https://pay.anore.cc/e2dfaa6e',
        'expiresIn': 14400,
    }


@pytest.mark.anyio
async def test_create_payment_uses_documented_wire_fields() -> None:
    service = RecordingService(_created())

    await service.create_payment(
        amount_kopeks=12345,
        description='Пополнение',
        order_id='an123_test',
        email='buyer@example.com',
        methods='sbp,crypto',
        success_url='https://web.example/success',
        fail_url='https://web.example/fail',
        callback_url='https://hooks.example/anore-webhook',
    )

    call = service.calls[0]
    assert call['method'] == 'POST'
    assert call['path'] == '/payments'
    assert call['payload'] == {
        'amount': 123.45,
        'currency': 'RUB',
        'description': 'Пополнение',
        'orderId': 'an123_test',
        'shopId': 42,
        'email': 'buyer@example.com',
        'methods': 'sbp,crypto',
        'successurl': 'https://web.example/success',
        'getbackurl': 'https://web.example/success',
        'failurl': 'https://web.example/fail',
        'callbackUrl': 'https://hooks.example/anore-webhook',
    }


@pytest.mark.anyio
async def test_create_payment_omits_optional_shop_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, 'ANORE_SHOP_ID', None, raising=False)
    service = RecordingService(_created())

    await service.create_payment(amount_kopeks=10000, description='X', order_id='order-1')

    assert 'shopId' not in service.calls[0]['payload']


@pytest.mark.anyio
async def test_create_payment_rejects_incomplete_response() -> None:
    service = RecordingService({'success': True, 'id': 'payment-id'})

    with pytest.raises(AnoreAPIError):
        await service.create_payment(amount_kopeks=10000, description='X', order_id='order-1')


@pytest.mark.anyio
async def test_get_payment_path() -> None:
    service = RecordingService({'id': 'payment-id', 'status': 'new'})

    await service.get_payment('payment-id')

    assert service.calls[0]['method'] == 'GET'
    assert service.calls[0]['path'] == '/payments/payment-id'


def test_headers_use_bearer_and_sign_exact_body() -> None:
    body = b'{"amount":100}'
    headers = AnoreService()._headers(body)

    assert headers['Authorization'] == 'Bearer an_test_key'
    assert headers['Anore-Signature'] == hmac.new(b'cashbox-secret', body, hashlib.sha256).hexdigest()


def test_webhook_signature_is_fail_closed() -> None:
    body = b'{"event":"payment.succeeded"}'
    signature = hmac.new(b'cashbox-secret', body, hashlib.sha256).hexdigest()
    service = AnoreService()

    assert service.verify_webhook_signature(body, signature) is True
    assert service.verify_webhook_signature(body + b' ', signature) is False
    assert service.verify_webhook_signature(body, None) is False
